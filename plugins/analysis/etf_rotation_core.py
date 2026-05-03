"""
ETF 轮动：指标、相关性、评分与过滤（供研究与回测共用）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.rotation_config_loader import load_rotation_config

from plugins.analysis.rotation_feature_cache import (
    fingerprint_58_cache,
    last_bar_yyyymmdd_from_df,
    save_58,
    try_load_58,
)


@dataclass
class EtfRotationRow:
    symbol: str
    pool_type: str
    momentum_5d: float
    momentum_20d: float
    momentum_60d: float
    vol_20d: float
    vol20_percentile: float
    max_drawdown_60d: float
    win_rate_20d: float
    trend_r2: float
    mean_abs_corr: float
    stability_score: float
    above_ma: Optional[bool]
    legacy_score: float
    score: float
    excluded: bool = False
    exclude_reason: Optional[str] = None
    soft_penalties: Dict[str, float] = field(default_factory=dict)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_structured_rotation_warnings(
    *,
    errors: List[str],
    corr_warnings: List[str],
    min_history_days: int,
    correlation_lookback_config: int,
) -> List[Dict[str, Any]]:
    """
    可机读告警：insufficient_history、correlation_window_reduced 等（供 L4 data_quality 审计）。
    """
    out: List[Dict[str, Any]] = []
    ins_re = re.compile(r"^([^:]+):\s*insufficient rows \((\d+)\s*<\s*(\d+)\)\s*$")
    for e in errors or []:
        if not isinstance(e, str):
            continue
        m = ins_re.match(e.strip())
        if not m:
            continue
        sym, actual_s, thr_s = m.group(1), m.group(2), m.group(3)
        actual, thr = int(actual_s), int(thr_s)
        out.append(
            {
                "code": "insufficient_history",
                "policy": "excluded_from_primary_scoring",
                "symbol": sym,
                "actual_window_days": actual,
                "threshold_days": thr,
                "message": (
                    f"{sym}: 实际使用窗口={actual}日（低于主榜阈值{thr}日），"
                    "主榜/因子可信度降低；已从主榜计分排除。"
                ),
            }
        )
    corr_pat = re.compile(r"^correlation_lookback_auto_reduced[^:]*:(\d+)\s*->\s*(\d+)\s*$")
    seen: set[Tuple[int, int]] = set()
    for cw in corr_warnings or []:
        if not isinstance(cw, str):
            continue
        m = corr_pat.match(cw.strip())
        if not m:
            continue
        req, act = int(m.group(1)), int(m.group(2))
        if (req, act) in seen:
            continue
        seen.add((req, act))
        out.append(
            {
                "code": "correlation_window_reduced",
                "policy": "correlation_window_reduced",
                "requested_window": req,
                "actual_window": act,
                "configured_correlation_lookback": correlation_lookback_config,
                "min_history_threshold": min_history_days,
                "message": (
                    f"相关性计算窗口由{req}个交易日收缩为{act}（交叉市场/日期对齐约束），"
                    "相关性矩阵可信度下降。"
                ),
            }
        )
    return out


def resolve_etf_pool(etf_pool: Optional[str], config: Dict[str, Any]) -> List[str]:
    """非空 etf_pool 优先；否则按配置多源合并（静态/环境变量/观察池）。"""
    if etf_pool is not None and str(etf_pool).strip():
        return [s.strip() for s in str(etf_pool).split(",") if s.strip()]

    from src.symbols_loader import load_symbols_config

    pool_cfg = config.get("pool") or {}
    # 主榜计分池可与「行业 RPS 映射全市场」解耦：未配置时回退 symbol_groups
    groups = pool_cfg.get("primary_scoring_symbol_groups") or pool_cfg.get("symbol_groups") or ["core", "industry_etf"]
    extras = pool_cfg.get("extra_etf_codes") or []
    sym_cfg = load_symbols_config()
    codes: List[str] = []
    for gname in groups:
        g = sym_cfg.get(gname)
        if g:
            codes.extend(list(g.etf_codes or []))
    codes.extend(str(x) for x in extras)
    merge_cfg = pool_cfg.get("merge_sources") or {}

    if bool(merge_cfg.get("env_enabled", True)):
        env_key = str(merge_cfg.get("env_var") or "ETF_CODES")
        env_raw = str(os.environ.get(env_key) or "").strip()
        if env_raw:
            codes.extend([x.strip() for x in env_raw.split(",") if x.strip()])

    if bool(merge_cfg.get("watchlist_enabled", True)):
        watch_paths = merge_cfg.get("watchlist_paths") or [
            "data/decisions/watchlist/current.json",
            "data/watchlist/default.json",
        ]
        max_watch_items = int(merge_cfg.get("watchlist_max_items") or 10)
        for rel in watch_paths:
            p = _project_root() / str(rel)
            if not p.exists():
                continue
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            watchlist = obj.get("watchlist") if isinstance(obj.get("watchlist"), list) else []
            if not watchlist and isinstance(obj.get("symbols"), list):
                watchlist = [{"symbol": x} for x in obj.get("symbols") if isinstance(x, str)]
            loaded = 0
            for item in watchlist:
                if not isinstance(item, dict):
                    continue
                sym = str(item.get("symbol") or "").strip()
                if sym:
                    codes.append(sym)
                    loaded += 1
                if loaded >= max_watch_items:
                    break
            if loaded > 0:
                break

    seen: set[str] = set()
    out: List[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    max_size = int(merge_cfg.get("max_size") or 30)
    return out[:max_size]


def resolve_pool_type_map(symbols: List[str], config: Dict[str, Any]) -> Dict[str, str]:
    """给候选代码打上池标签（industry/concept/extra/unknown）。"""
    from src.symbols_loader import load_symbols_config

    sym_cfg = load_symbols_config()
    groups = config.get("pool", {}).get("symbol_groups") or []
    out: Dict[str, str] = {}
    for s in symbols:
        tag = "unknown"
        for gname in groups:
            g = sym_cfg.get(str(gname))
            if g and s in (g.etf_codes or []):
                if gname == "industry_etf":
                    tag = "industry"
                elif gname == "concept_etf":
                    tag = "concept"
                else:
                    tag = str(gname)
                break
        if tag == "unknown":
            extras = [str(x) for x in (config.get("pool", {}).get("extra_etf_codes") or [])]
            if s in extras:
                tag = "extra"
        out[s] = tag
    return out


def compute_data_need(config: Dict[str, Any], lookback_days: int) -> int:
    f = config.get("filters") or {}
    ma = int(f.get("ma_period") or 200)
    corr = int(f.get("correlation_lookback") or 252)
    tr2 = int(f.get("trend_r2_window") or 60)
    min_h = int(f.get("min_history_days") or 70)
    lb = int(lookback_days) if lookback_days else 0
    return max(min_h, ma + 1, corr + 5, tr2 + 5, lb)


def trim_dataframe(df: pd.DataFrame, lookback_days: int, data_need: int) -> pd.DataFrame:
    need = max(int(lookback_days or 0), int(data_need))
    if need > 0 and len(df) > need:
        return df.iloc[-need:].copy()
    return df


def extract_close_series(df: pd.DataFrame) -> Tuple[pd.Series, Optional[str]]:
    cols = {c.lower(): c for c in df.columns}
    close_col = cols.get("close") or cols.get("收盘") or cols.get("收盘价")
    if not close_col:
        raise ValueError("close column not found")
    date_col = None
    for c in df.columns:
        if str(c).lower() in ("date", "日期", "trade_date", "datetime", "时间"):
            date_col = c
            break
    s = pd.to_numeric(df[close_col], errors="coerce")
    if date_col:
        dt = pd.to_datetime(df[date_col], errors="coerce")
        s = pd.Series(s.values, index=dt)
        s = s[~s.index.duplicated(keep="last")].sort_index()
    else:
        s = s.reset_index(drop=True)
    s = s.dropna()
    if len(s) < 2:
        raise ValueError("insufficient close points")
    return s, date_col


def _legacy_score(m20: float, m60: float, vol20: float, mdd60: float, leg: Dict[str, float]) -> float:
    return (
        float(leg.get("w_m20", 0.45)) * m20
        + float(leg.get("w_m60", 0.35)) * m60
        - float(leg.get("w_vol", 0.15)) * vol20
        + float(leg.get("w_mdd", 0.05)) * mdd60
    )


def _trend_r2_log(s: pd.Series, window: int) -> float:
    if len(s) < window:
        return 0.0
    y = np.log(np.maximum(s.iloc[-window:].astype(float).values, 1e-12))
    x = np.arange(len(y), dtype=float)
    if len(y) < 3:
        return 0.0
    coef = np.polyfit(x, y, 1)
    y_pred = np.polyval(coef, x)
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    if ss_tot <= 1e-18:
        return 0.0
    return max(0.0, min(1.0, 1.0 - ss_res / ss_tot))


def _safe_percentile(v: float, arr: np.ndarray) -> float:
    if arr.size == 0:
        return 0.5
    return float(np.mean(arr <= v))


def compute_base_metrics(
    s: pd.Series,
    symbol: str,
    min_rows: int,
    *,
    crowd_window: int = 60,
) -> Tuple[float, float, float, float, float, float, float]:
    if len(s) < min_rows:
        raise ValueError(f"{symbol}: insufficient rows ({len(s)} < {min_rows})")
    m5 = float(s.iloc[-1] / s.iloc[-6] - 1.0)
    m20 = float(s.iloc[-1] / s.iloc[-21] - 1.0)
    m60 = float(s.iloc[-1] / s.iloc[-61] - 1.0)
    rets = s.pct_change().dropna()
    vol20 = float(rets.iloc[-20:].std(ddof=0) * np.sqrt(252))
    win_rate_20d = float((rets.iloc[-20:] > 0).mean()) if len(rets) >= 20 else 0.5
    rolling_vol20 = rets.rolling(20).std(ddof=0) * np.sqrt(252)
    rv = rolling_vol20.dropna().values
    if rv.size >= crowd_window:
        rv = rv[-crowd_window:]
    crowding = _safe_percentile(vol20, rv) if rv.size else 0.5
    window = s.iloc[-60:]
    roll_max = window.cummax()
    dd = (window / roll_max) - 1.0
    mdd60 = float(dd.min())
    return m5, m20, m60, vol20, crowding, mdd60, win_rate_20d


def _safe_last_float(s: pd.Series) -> float | None:
    """Return the last non-null float value."""
    try:
        s2 = pd.to_numeric(s, errors="coerce")
        v = s2.dropna().iloc[-1] if len(s2.dropna()) else None
        if v is None:
            return None
        x = float(v)
        if np.isnan(x):
            return None
        return x
    except Exception:
        return None


def _normalize_ohlcv_df_for_tech(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame | None, str | None]:
    """
    Normalize input OHLCV columns into lower-case: open/high/low/close/volume (if present).
    We only require high/low/close for P0 minimal features.
    """
    rename_map = {
        "date": "date",
        "日期": "date",
        "trade_date": "date",
        "datetime": "date",
        "时间": "date",
        "open": "open",
        "开盘": "open",
        "high": "high",
        "最高": "high",
        "low": "low",
        "最低": "low",
        "close": "close",
        "收盘": "close",
        "收盘价": "close",
        "volume": "volume",
        "成交量": "volume",
    }
    if df is None or getattr(df, "empty", True):
        return None, "empty_df"

    out = df.copy()
    cols_lower = {str(c).lower(): c for c in out.columns}
    # Rename date + ohlc keys if present in multiple languages.
    for k, v in rename_map.items():
        if k in out.columns and v not in out.columns:
            out[v] = out[k]
        elif k in cols_lower and v not in out.columns:
            out[v] = out[cols_lower[k]]

    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    required = ["high", "low", "close"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        return None, f"missing_columns:{','.join(missing)}"

    # Drop rows without close to keep indicator alignment consistent.
    out = out.dropna(subset=["close", "high", "low"], how="any").reset_index(drop=True)
    if len(out) < 30:
        return None, f"insufficient_rows:{len(out)}"
    return out, None


def extract_58_features(
    df: pd.DataFrame,
    *,
    symbol: str,
    engine_preference: str = "auto",
    macd_factor: float = 2.0,
) -> Tuple[Dict[str, float] | None, List[str]]:
    """
    Extract P0 minimal features from OHLCV series using TA-Lib priority and pandas-ta fallback.
    This intentionally computes only the indicators needed for the first-stage score mapping:
    MACD/RSI/ADX/NATR/BBANDS.

    Returns:
      (features, warnings)
      - features: dict with normalized numeric fields for scoring
      - warnings: extraction warnings for the caller to surface (but never fails the whole pipeline)
    """
    warnings: List[str] = []
    try:
        norm, msg = _normalize_ohlcv_df_for_tech(df)
        if norm is None:
            return None, [f"{symbol}:{msg}"]

        close = norm["close"].astype("float64")
        high = norm["high"].astype("float64")
        low = norm["low"].astype("float64")

        # Select engine once per symbol.
        from plugins.data_collection.technical_indicators.engine import TechnicalIndicatorEngine

        sel = TechnicalIndicatorEngine.select(engine_preference)

        macd_diff = macd_dea = macd_hist = None
        rsi_14 = adx_14 = None
        natr_14 = None
        bb_upper = bb_middle = bb_lower = None

        if sel.name == "talib" and sel.talib is not None:
            ta = sel.talib
            macd, macd_signal, macd_hist_s = ta.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
            macd_diff = macd
            macd_dea = macd_signal
            macd_hist = macd_hist_s
            rsi_14 = ta.RSI(close, timeperiod=14)
            adx_14 = ta.ADX(high, low, close, timeperiod=14)
            natr_14 = ta.NATR(high, low, close, timeperiod=14)
            up, mid, dn = ta.BBANDS(close, timeperiod=20, nbdevup=2.0, nbdevdn=2.0, matype=0)
            bb_upper, bb_middle, bb_lower = up, mid, dn
        elif sel.name == "pandas_ta" and sel.pandas_ta is not None:
            pta = sel.pandas_ta
            macd_df = pta.macd(close, fast=12, slow=26, signal=9)
            if macd_df is None or macd_df.empty:
                raise RuntimeError("pandas_ta.macd empty")
            macd_diff = macd_df.iloc[:, 0]
            macd_hist = macd_df.iloc[:, 1]
            macd_dea = macd_df.iloc[:, 2]
            rsi_14 = pta.rsi(close, length=14)
            adx_df = pta.adx(high, low, close, length=14)
            adx_14 = adx_df.iloc[:, 0] if adx_df is not None and not adx_df.empty else None
            natr_14 = pta.natr(high, low, close, length=14)
            bb_df = pta.bbands(close, length=20, std=2.0)
            if bb_df is None or bb_df.empty or bb_df.shape[1] < 3:
                raise RuntimeError("pandas_ta.bbands empty")
            bb_lower = bb_df.iloc[:, 0]
            bb_middle = bb_df.iloc[:, 1]
            bb_upper = bb_df.iloc[:, 2]
        else:
            # Builtin minimal formulas when neither TA-Lib nor pandas-ta is available.
            from plugins.data_collection.technical_indicators.indicators import _adx_builtin, _rsi_builtin

            # MACD
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_diff = ema12 - ema26
            macd_dea = macd_diff.ewm(span=9, adjust=False).mean()
            macd_hist = macd_diff - macd_dea
            # Domestic alignment (match tool default macd_factor=2.0)
            macd_diff = macd_diff * macd_factor
            macd_hist = macd_hist * macd_factor

            rsi_14 = _rsi_builtin(close, 14)
            adx_14 = _adx_builtin(high, low, close, 14)

            # ATR & NATR
            prev_close = close.shift(1)
            tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
            atr_14 = tr.rolling(14).mean()
            natr_14 = (atr_14 / close.replace(0, np.nan)) * 100.0

            # BBANDS
            bb_middle = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            bb_upper = bb_middle + 2.0 * bb_std
            bb_lower = bb_middle - 2.0 * bb_std

        # Apply domestic alignment for non-builtin branches.
        if sel.name in ("talib", "pandas_ta"):
            macd_diff = macd_diff * macd_factor
            macd_hist = macd_hist * macd_factor

        # Extract last valid values.
        macd_diff_v = _safe_last_float(macd_diff)
        macd_dea_v = _safe_last_float(macd_dea)
        macd_hist_v = _safe_last_float(macd_hist)
        rsi_v = _safe_last_float(rsi_14)
        adx_v = _safe_last_float(adx_14)
        natr_v = _safe_last_float(natr_14)
        bu_v = _safe_last_float(bb_upper)
        bm_v = _safe_last_float(bb_middle)
        bl_v = _safe_last_float(bb_lower)
        close_v = _safe_last_float(close)

        if None in (macd_diff_v, macd_dea_v, macd_hist_v, rsi_v, adx_v, natr_v, bu_v, bm_v, bl_v, close_v):
            return None, [f"{symbol}:indicator_last_nan"]

        # State derivation (b1: MACD/RSI/ADX/ATR/BBANDS).
        macd_trend_score = 0.0
        if macd_diff_v > macd_dea_v and macd_hist_v > 0:
            macd_trend_score = 1.0
        elif macd_diff_v < macd_dea_v and macd_hist_v < 0:
            macd_trend_score = -1.0

        rsi_state_score = 0.0
        if 50.0 <= rsi_v < 70.0:
            rsi_state_score = 1.0
        elif rsi_v >= 70.0:
            rsi_state_score = 0.0  # overbought: no direct bonus
        elif rsi_v < 45.0:
            rsi_state_score = -1.0

        # Trend strength from ADX.
        trend_strength_score = 0.2
        if adx_v >= 25.0:
            trend_strength_score = 1.0
        elif adx_v >= 20.0:
            trend_strength_score = 0.6

        # NATR to volatility penalty proxy.
        natr_score = max(0.0, min(1.0, natr_v / 100.0))

        # Boll band position proxy (optional; only for debugging/report hooks).
        boll_position_score = 0.0
        if close_v >= bu_v:
            boll_position_score = 0.0  # near/over upper band: treat as neutral/overheat
        elif close_v >= bm_v:
            boll_position_score = 1.0
        elif close_v <= bl_v:
            boll_position_score = -1.0

        return {
            "macd_trend_score": float(macd_trend_score),
            "rsi_state_score": float(rsi_state_score),
            "trend_strength_score": float(trend_strength_score),
            "natr_score": float(natr_score),
            "boll_position_score": float(boll_position_score),
        }, []
    except Exception as e:  # noqa: BLE001
        return None, [f"{symbol}:extract_58_features_failed:{e}"]


def _rank_pct(values: Dict[str, float], reverse: bool = False) -> Dict[str, float]:
    if not values:
        return {}
    items = sorted(values.items(), key=lambda x: x[1], reverse=reverse)
    n = len(items)
    if n == 1:
        return {items[0][0]: 1.0}
    out: Dict[str, float] = {}
    for i, (k, _) in enumerate(items):
        out[k] = i / (n - 1)
    return out


def compute_stability_scores(
    symbols: List[str],
    history_runs: List[Dict[str, Any]],
    *,
    lookback_runs: int = 6,
) -> Dict[str, float]:
    """
    读取最近轮动记录，按排名波动给稳定性分数（0~1，越高越稳）。
    无历史记录时默认0.5。
    """
    if not symbols:
        return {}
    runs = history_runs[-lookback_runs:]
    if not runs:
        return {s: 0.5 for s in symbols}
    default_rank = len(symbols) + 5
    rank_hist: Dict[str, List[float]] = {s: [] for s in symbols}
    for run in runs:
        ranked = run.get("ranked_symbols")
        if isinstance(ranked, list) and ranked:
            rank_map = {str(sym): idx + 1 for idx, sym in enumerate(ranked)}
        else:
            top = run.get("top_symbols") or []
            rank_map = {str(sym): idx + 1 for idx, sym in enumerate(top)}
        for s in symbols:
            rank_hist[s].append(float(rank_map.get(s, default_rank)))
    stds: Dict[str, float] = {}
    for s, vals in rank_hist.items():
        arr = np.array(vals, dtype=float)
        stds[s] = float(arr.std(ddof=0)) if arr.size > 1 else 0.5
    inv = {s: 1.0 / (v + 0.01) for s, v in stds.items()}
    mn, mx = min(inv.values()), max(inv.values())
    if abs(mx - mn) < 1e-12:
        return {s: 0.5 for s in symbols}
    return {s: (inv[s] - mn) / (mx - mn) for s in symbols}


def compute_ma_above(s: pd.Series, ma_period: int) -> Optional[bool]:
    if len(s) < ma_period + 1:
        return None
    ma = float(s.iloc[-ma_period:].mean())
    return bool(float(s.iloc[-1]) > ma)


def load_etf_daily_df(
    symbol: str,
    *,
    start_yyyymmdd: str,
    end_yyyymmdd: str,
    allow_online_backfill: bool = True,
) -> Tuple[Optional[pd.DataFrame], Optional[str], str]:
    """
    读取 ETF 日线（联合口径）：
    - 优先读缓存；
    - 缓存缺失/不完整时在线补采并回写缓存；
    - 允许部分缓存命中（与研究/回测一致），但会返回 message/source 供上层审计。
    """
    from data_access.read_cache_data import read_cache_data
    from plugins.data_collection.etf.fetch_historical import fetch_single_etf_historical

    out = read_cache_data(
        data_type="etf_daily",
        symbol=symbol,
        start_date=start_yyyymmdd,
        end_date=end_yyyymmdd,
        return_df=True,
        # 避免 read_cache 内 _try_refill 与下方 fetch_single 对同区间连续拉两次源站
        skip_online_refill=True,
    )
    missing_dates = list(out.get("missing_dates") or [])
    # 纠偏：非交易时段/非交易日手动触发时，end_date 可能落在未来或周末，
    # read_cache_data 会把“未来日期”算入 missing_dates，进而触发不必要的在线补采（极慢且易限流）。
    # 若缓存已包含最近有效交易日数据，则忽略 last_bar 之后的 missing_dates。
    try:
        df0 = out.get("df")
        if missing_dates and df0 is not None and not getattr(df0, "empty", True):
            last_bar = last_bar_yyyymmdd_from_df(df0)
            if last_bar and str(last_bar).isdigit() and len(str(last_bar)) == 8:
                missing_dates = [d for d in missing_dates if str(d) <= str(last_bar)]
    except Exception:
        pass
    if out.get("success") and not missing_dates:
        return out.get("df"), None, "cache"
    df = out.get("df")
    # cache-only mode: return cache hit (even partial) and never call online sources.
    if not allow_online_backfill:
        if df is not None and not (hasattr(df, "empty") and df.empty):
            return df, out.get("message") or "cache_only_partial", "cache_partial"
        return None, out.get("message") or "cache_only_miss", "failed"
    if df is not None and not (hasattr(df, "empty") and df.empty):
        # 缓存部分命中，尝试仅补缺口区间（避免拉取过大窗口）
        try:
            if missing_dates:
                fb_start = min(missing_dates)
                fb_end = max(missing_dates)
            else:
                fb_start, fb_end = start_yyyymmdd, end_yyyymmdd
            fetched, src = fetch_single_etf_historical(
                etf_code=str(symbol),
                period="daily",
                start_date=f"{fb_start[:4]}-{fb_start[4:6]}-{fb_start[6:]}",
                end_date=f"{fb_end[:4]}-{fb_end[4:6]}-{fb_end[6:]}",
                use_cache=True,
            )
            if fetched is not None and not fetched.empty:
                # fetch_single_etf_historical 内部会合并+回写缓存；这里直接返回 merged 口径
                try:
                    merged = df
                    # 简单 merge：按日期列去重拼接（若无日期列则退化为直接返回 fetched）
                    date_col = None
                    for c in ["日期", "date", "trade_date", "datetime", "时间"]:
                        if c in fetched.columns and c in merged.columns:
                            date_col = c
                            break
                    if date_col:
                        merged = (
                            pd.concat([merged, fetched], ignore_index=True)
                            .drop_duplicates(subset=[date_col], keep="last")
                            .sort_values(by=[date_col])
                        )
                    else:
                        merged = fetched
                except Exception:
                    merged = fetched
                return merged, out.get("message") or "partial_cache_backfilled", f"cache+online:{src or 'unknown'}"
        except Exception:
            # 在线补采失败不影响返回已有缓存
            return df, out.get("message") or "partial_cache", "cache_partial"
        return df, out.get("message") or "partial_cache", "cache_partial"

    # 缓存无数据：在线补采（全量区间或缺口区间）
    try:
        fb_start, fb_end = start_yyyymmdd, end_yyyymmdd
        if missing_dates:
            fb_start = min(missing_dates)
            fb_end = max(missing_dates)
        fetched, src = fetch_single_etf_historical(
            etf_code=str(symbol),
            period="daily",
            start_date=f"{fb_start[:4]}-{fb_start[4:6]}-{fb_start[6:]}",
            end_date=f"{fb_end[:4]}-{fb_end[4:6]}-{fb_end[6:]}",
            use_cache=True,
        )
        if fetched is not None and not fetched.empty:
            return fetched, out.get("message") or "cache_miss_backfilled", f"online:{src or 'unknown'}"
    except Exception as e:  # noqa: BLE001
        return None, f"{out.get('message') or 'cache_miss'}; online_backfill_failed: {e}", "failed"

    return None, out.get("message"), "failed"


def _prefetch_etf_daily_frames(
    symbols: List[str],
    start_d: str,
    end_d: str,
    *,
    allow_online_backfill: bool = True,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[str], str]]:
    """
    并行加载各标的 ETF 日线（I/O 为主）。可通过环境变量关闭并行：
    - ETF_ROTATION_LOAD_MAX_WORKERS=1：完全串行（与旧行为一致）
    - 未设置或为空：默认 min(8, len(symbols))
    - 其他正整数：显式上限
    """
    if not symbols:
        return {}

    def _one(sym: str) -> Tuple[str, Optional[pd.DataFrame], Optional[str], str]:
        df, msg, src = load_etf_daily_df(
            sym,
            start_yyyymmdd=start_d,
            end_yyyymmdd=end_d,
            allow_online_backfill=allow_online_backfill,
        )
        return sym, df, msg, src

    raw = os.environ.get("ETF_ROTATION_LOAD_MAX_WORKERS", "").strip()
    # Cache-only mode is I/O-bound and can suffer from lock/contention when many workers
    # hit the same cache backend concurrently; default to sequential unless explicitly overridden.
    if (not allow_online_backfill) and raw == "":
        raw = "1"
    if raw == "1":
        out: Dict[str, Tuple[Optional[pd.DataFrame], Optional[str], str]] = {}
        for sym in symbols:
            _, df, msg, src = _one(sym)
            out[sym] = (df, msg, src)
        return out

    try:
        max_workers = int(raw) if raw.isdigit() else min(8, max(1, len(symbols)))
    except ValueError:
        max_workers = min(8, max(1, len(symbols)))
    max_workers = max(1, min(max_workers, len(symbols)))

    acc: Dict[str, Tuple[Optional[pd.DataFrame], Optional[str], str]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_one, sym): sym for sym in symbols}
        for fut in as_completed(futures):
            sym, df, msg, src = fut.result()
            acc[sym] = (df, msg, src)
    return acc


def default_load_date_range(
    *,
    as_of_yyyymmdd: Optional[str] = None,
    calendar_days_back: int = 900,
) -> Tuple[str, str]:
    end = as_of_yyyymmdd or datetime.now().strftime("%Y%m%d")
    start_dt = datetime.strptime(end, "%Y%m%d") - timedelta(days=calendar_days_back)
    return start_dt.strftime("%Y%m%d"), end


def build_log_returns_aligned(
    close_by_symbol: Dict[str, pd.Series],
    lookback: int,
) -> Tuple[Optional[pd.DataFrame], List[str]]:
    """
    对齐各标的收盘价：优先用日期索引交集；否则用末尾同长度切片（位置对齐）。

    混池（A 股 / 港股 ETF）时，日历交集往往远短于单标的序列长度；会在交集上自动收缩
    lookback，必要时回退到尾部位置对齐，避免相关性整块跳过、mean_abs_corr 全为 0。
    """
    warnings: List[str] = []
    if len(close_by_symbol) < 2:
        return None, warnings

    syms = list(close_by_symbol.keys())
    lookback = int(lookback)
    all_dt = all(isinstance(close_by_symbol[s].index, pd.DatetimeIndex) for s in syms)

    def _need_calendar_days(lb: int) -> int:
        return max(lb + 2, 10)

    def _cap_lookback_for_rows(n_rows: int, lb: int) -> int:
        """n_rows: 对齐后可用的收盘行数。对数收益至少需要 lb+1 行。"""
        if n_rows < 13:
            return lb
        cap = max(10, n_rows - 3)
        return min(lb, cap)

    aligned: Dict[str, pd.Series]
    use_calendar = False

    if all_dt:
        common_idx = close_by_symbol[syms[0]].index
        for s in syms[1:]:
            common_idx = common_idx.intersection(close_by_symbol[s].index)
        common_len = len(common_idx)

        # 先按交集长度收缩 lookback（关键：eff_lb 只看单序列长度会高估交集）
        capped = _cap_lookback_for_rows(common_len, lookback)
        if capped < lookback:
            warnings.append(f"correlation_lookback_auto_reduced:{lookback}->{capped}")
            lookback = capped

        need = _need_calendar_days(lookback)
        if common_len >= need:
            wide = pd.DataFrame(
                {
                    s: close_by_symbol[s].reindex(common_idx).sort_index().ffill(limit=5).bfill(limit=5)
                    for s in syms
                }
            )
            wide = wide.dropna(how="any")
            inner_len = int(len(wide))
            if inner_len < need:
                capped2 = _cap_lookback_for_rows(inner_len, lookback)
                if capped2 < lookback:
                    warnings.append(f"correlation_lookback_auto_reduced_after_align:{lookback}->{capped2}")
                    lookback = capped2
                need = _need_calendar_days(lookback)
            if inner_len >= need:
                aligned = {s: wide[s] for s in syms}
                use_calendar = True

        if not use_calendar:
            warnings.append("correlation_fell_back_to_positional_align")

    if not use_calendar:
        # 位置对齐：取各标的尾部同长度窗口（跨市场日历无法逐日对齐时的近似）
        min_len = min(len(close_by_symbol[s].dropna()) for s in syms)
        capped = _cap_lookback_for_rows(min_len, lookback)
        if capped < lookback:
            warnings.append(f"correlation_lookback_auto_reduced_pos:{lookback}->{capped}")
            lookback = capped
        if min_len < _need_calendar_days(lookback):
            warnings.append("positional_align_too_short")
            return None, warnings
        aligned = {
            s: close_by_symbol[s].dropna().iloc[-min_len:].reset_index(drop=True) for s in syms
        }

    rets_data: Dict[str, np.ndarray] = {}
    for sym, s in aligned.items():
        tail = s.iloc[-(lookback + 1) :].astype(float)
        lr = np.log(tail.clip(lower=1e-12)).diff().dropna()
        arr = lr.values[-lookback:] if len(lr) >= lookback else lr.values
        rets_data[sym] = arr

    min_r = min(len(v) for v in rets_data.values())
    if min_r < 10:
        return None, warnings + ["corr_returns_too_short"]
    rets = pd.DataFrame({s: rets_data[s][-min_r:] for s in syms})
    return rets, warnings


def correlation_matrix_and_mean_abs(rets: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, float]]:
    corr = rets.corr()
    mean_abs: Dict[str, float] = {}
    for sym in corr.index:
        row = corr.loc[sym].drop(labels=[sym], errors="ignore")
        if len(row) == 0:
            mean_abs[sym] = 0.0
        else:
            mean_abs[sym] = float(np.mean(np.abs(row.values)))
    return corr, mean_abs


def apply_correlation_filter_greedy(
    symbols_sorted_by_score: List[str],
    corr: pd.DataFrame,
    pairwise_max: float,
) -> List[str]:
    """得分降序贪心：与已选集合任一对 |rho|>=pairwise_max 则跳过。"""
    kept: List[str] = []
    for sym in symbols_sorted_by_score:
        ok = True
        for k in kept:
            try:
                rho = abs(float(corr.loc[sym, k]))
            except Exception:
                rho = 0.0
            if rho >= pairwise_max:
                ok = False
                break
        if ok:
            kept.append(sym)
    return kept


def composite_raw_score(
    m20: float,
    m60: float,
    vol20: float,
    mdd60: float,
    trend_r2: float,
    mean_abs_corr: float,
    fac: Dict[str, float],
    *,
    use_trend: bool,
    use_corr_penalty: bool,
) -> float:
    w = fac
    sc = (
        float(w.get("w_m20", 0.3)) * m20
        + float(w.get("w_m60", 0.25)) * m60
        - float(w.get("w_vol", 0.15)) * vol20
        + float(w.get("w_mdd", 0.05)) * mdd60
    )
    if use_trend:
        sc += float(w.get("w_trend_r2", 0.1)) * trend_r2
    if use_corr_penalty:
        sc -= float(w.get("w_corr_penalty", 0.2)) * mean_abs_corr
    return float(sc)


def composite_raw_score_58(
    m20: float,
    m60: float,
    vol20: float,
    mdd60: float,
    trend_r2: float,
    mean_abs_corr: float,
    tech_feats: Dict[str, float] | None,
    fac: Dict[str, float],
    *,
    use_trend: bool,
    use_corr_penalty: bool,
) -> Tuple[float, bool]:
    """
    First-stage score mapping using P0 minimal 58-indicator features.

    Returns: (score, used_58)
    - If tech_feats is None, caller should fall back to legacy score inputs.
    """
    if not tech_feats:
        return composite_raw_score(
            m20, m60, vol20, mdd60, trend_r2, mean_abs_corr, fac, use_trend=use_trend, use_corr_penalty=use_corr_penalty
        ), False

    # Map features to the existing composite score inputs with minimal disruption:
    # - momentum components: macd_trend_score + rsi_state_score
    # - volatility component: natr_score (proxy)
    # - trend component: trend_strength_score (0~1)
    macd_trend_score = float(tech_feats.get("macd_trend_score", 0.0))
    rsi_state_score = float(tech_feats.get("rsi_state_score", 0.0))
    tech_momentum_state = 0.5 * macd_trend_score + 0.5 * rsi_state_score  # [-1,1]

    m20_new = tech_momentum_state * abs(float(m20))
    m60_new = tech_momentum_state * abs(float(m60))
    vol20_new = float(tech_feats.get("natr_score", 0.0))
    trend_r2_new = float(tech_feats.get("trend_strength_score", 0.0))

    sc = composite_raw_score(
        m20_new,
        m60_new,
        vol20_new,
        mdd60,
        trend_r2_new,
        mean_abs_corr,
        fac,
        use_trend=use_trend,
        use_corr_penalty=use_corr_penalty,
    )
    return float(sc), True


def _safe_norm01(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.5
    x = (float(value) - float(low)) / (float(high) - float(low))
    return max(0.0, min(1.0, x))


def run_rotation_pipeline(
    symbols: List[str],
    config: Dict[str, Any],
    *,
    lookback_days: int = 120,
    as_of_yyyymmdd: Optional[str] = None,
    score_engine: str = "legacy",
    runtime_inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    加载日线、计算指标、相关性与最终排名。
    """
    feats = config.get("features") or {}
    fcfg = config.get("filters") or {}
    fac = config.get("factors") or {}
    leg_fac = config.get("legacy_factors") or {}
    crowd_cfg = config.get("crowding") or {}
    de_cfg = config.get("degradation") or {}

    data_need = compute_data_need(config, lookback_days)
    # 用“所需交易日 * 系数”的日历天数回看，避免固定回看6年导致缓存补采与校验极慢/易失败。
    # 经验：1个交易日≈1.4-1.6个日历日；这里取 2x 并保留最小兜底，降低读盘压力。
    cal_back = max(300, int(data_need) * 2)
    # 防止极端配置导致过大回看
    cal_back = min(cal_back, 1200)
    start_d, end_d = default_load_date_range(as_of_yyyymmdd=as_of_yyyymmdd, calendar_days_back=cal_back)

    rows: List[EtfRotationRow] = []
    errors: List[str] = []
    close_by_symbol: Dict[str, pd.Series] = {}
    pool_type_map = resolve_pool_type_map(symbols, config)
    load_health: Dict[str, Dict[str, Any]] = {}
    tech_features_by_sym: Dict[str, Dict[str, float] | None] = {}
    min_rows = int(fcfg.get("min_history_days") or 70)
    ma_period = int(fcfg.get("ma_period") or 200)
    tr_w = int(fcfg.get("trend_r2_window") or 60)
    corr_lb = int(fcfg.get("correlation_lookback") or 252)
    corr_mode = str(fcfg.get("correlation_mode") or "penalize")
    corr_thr = float(fcfg.get("correlation_threshold") or 0.7)
    pairwise_max = float(fcfg.get("correlation_pairwise_max") or 0.85)
    ma_mode = str(fcfg.get("ma_mode") or "soft")
    ma_pen = float(fcfg.get("ma_below_penalty") or 0.5)
    vol_min, vol_max = float(fcfg.get("vol_min") or 0.0), float(fcfg.get("vol_max") or 1.0)
    vol_gate = str(fcfg.get("vol_gate_mode") or "off")
    vol_soft = float(fcfg.get("vol_soft_penalty") or 0.5)
    mdd_thr = float(fcfg.get("mdd60_threshold") or -0.99)
    mdd_gate = str(fcfg.get("mdd_gate_mode") or "off")
    mdd_soft = float(fcfg.get("mdd_soft_penalty") or 0.7)
    crowd_enabled = bool(crowd_cfg.get("enabled", False))
    crowd_window = int(crowd_cfg.get("window") or 60)
    crowd_soft_thr = float(crowd_cfg.get("soft_threshold") or 0.8)
    crowd_hard_thr = float(crowd_cfg.get("hard_threshold") or 0.95)
    crowd_penalty = float(crowd_cfg.get("penalty_factor") or 0.5)

    use_corr = bool(feats.get("use_correlation", True)) and corr_mode != "off"
    use_ma = bool(feats.get("use_ma", True)) and ma_mode != "off"
    use_tr2 = bool(feats.get("use_trend_r2", True))
    use_vg = bool(feats.get("use_vol_gate", False)) or vol_gate != "off"
    use_mdd = bool(feats.get("use_mdd_gate", False)) or mdd_gate != "off"

    macd_f = float((config.get("alignment") or {}).get("macd_factor") or 2.0)
    fp58 = fingerprint_58_cache(config, macd_f)

    ri = runtime_inputs if isinstance(runtime_inputs, dict) else {}
    allow_online_backfill = bool(ri.get("allow_online_backfill", True))
    prefetched = _prefetch_etf_daily_frames(symbols, start_d, end_d, allow_online_backfill=allow_online_backfill)

    for sym in symbols:
        df, msg, src = prefetched[sym]
        if df is None or df.empty:
            errors.append(f"{sym}: load failed: {msg}")
            load_health[sym] = {
                "ok": False,
                "message": msg or "load_failed",
                "source": src,
                "attempted_fallback_sources": ["mootdx", "tushare", "sina", "eastmoney"],
                "retry_policy": {"sina": 3, "eastmoney": 3},
            }
            continue
        df = trim_dataframe(df, lookback_days, data_need)
        try:
            s, _ = extract_close_series(df)
            if isinstance(s.index, pd.DatetimeIndex):
                close_by_symbol[sym] = s
            else:
                close_by_symbol[sym] = s
            m5, m20, m60, vol20, crowding, mdd60, win_rate_20d = compute_base_metrics(
                s, sym, min_rows, crowd_window=crowd_window
            )
            trend_r2 = _trend_r2_log(s, tr_w) if use_tr2 else 0.0
            above_ma = compute_ma_above(s, ma_period) if use_ma else None
            leg_score = _legacy_score(m20, m60, vol20, mdd60, leg_fac)

            # Extract minimal P0 features only when pilot score engine is enabled.
            if score_engine == "58":
                lb = last_bar_yyyymmdd_from_df(df)
                cached58 = try_load_58(sym, lb, fp58) if lb else None
                if cached58 is not None:
                    tech58, feats58_warn = cached58, []
                else:
                    tech58, feats58_warn = extract_58_features(
                        df,
                        symbol=sym,
                        engine_preference="auto",
                        macd_factor=macd_f,
                    )
                    if tech58 is not None and lb:
                        save_58(sym, lb, fp58, tech58)
                tech_features_by_sym[sym] = tech58
                if feats58_warn:
                    # Keep the pipeline running; surface it via warnings.
                    # (We cannot use errors list here because it would change task status.)
                    pass
            else:
                tech_features_by_sym[sym] = None

            rows.append(
                EtfRotationRow(
                    symbol=sym,
                    pool_type=pool_type_map.get(sym, "unknown"),
                    momentum_5d=m5,
                    momentum_20d=m20,
                    momentum_60d=m60,
                    vol_20d=vol20,
                    vol20_percentile=crowding,
                    max_drawdown_60d=mdd60,
                    win_rate_20d=win_rate_20d,
                    trend_r2=trend_r2,
                    mean_abs_corr=0.0,
                    stability_score=0.5,
                    above_ma=above_ma,
                    legacy_score=leg_score,
                    score=0.0,
                )
            )
            load_health[sym] = {
                "ok": True,
                "message": msg or "ok",
                "source": src,
                "rows": int(len(df)),
            }
        except Exception as e:
            errors.append(f"{sym}: {e}")
            load_health[sym] = {
                "ok": False,
                "message": str(e),
                "source": src,
                "attempted_fallback_sources": ["mootdx", "tushare", "sina", "eastmoney"],
                "retry_policy": {"sina": 3, "eastmoney": 3},
            }

    mean_abs_map: Dict[str, float] = {r.symbol: 0.0 for r in rows}
    corr_df: Optional[pd.DataFrame] = None
    corr_warnings: List[str] = []

    if use_corr and len(close_by_symbol) >= 2:
        eff_lb = min(corr_lb, max(30, min(len(s) for s in close_by_symbol.values()) - 2))
        rets_df, cw = build_log_returns_aligned(close_by_symbol, eff_lb)
        corr_warnings.extend(cw)
        if rets_df is not None and rets_df.shape[1] >= 2:
            corr_df, mean_abs_map = correlation_matrix_and_mean_abs(rets_df)
        else:
            corr_warnings.append("correlation_skipped")

    stability_map = compute_stability_scores(
        [r.symbol for r in rows],
        read_last_rotation_runs(8, config),
        lookback_runs=6,
    )
    for r in rows:
        r.mean_abs_corr = float(mean_abs_map.get(r.symbol, 0.0))
        r.stability_score = float(stability_map.get(r.symbol, 0.5))

    working: List[EtfRotationRow] = []
    tf_cfg = config.get("three_factor_v2") or {}
    tf_weights = tf_cfg.get("weights") or {}
    w_momentum = float(tf_weights.get("sector_momentum") or 0.40)
    w_resonance = float(tf_weights.get("capital_resonance") or 0.35)
    w_sentiment = float(tf_weights.get("sentiment") or 0.25)
    sentiment_inputs = (runtime_inputs or {}).get("sentiment") if isinstance(runtime_inputs, dict) else {}
    if not isinstance(sentiment_inputs, dict):
        sentiment_inputs = {}
    stage = str(sentiment_inputs.get("sentiment_stage") or "震荡期")
    dispersion = float(sentiment_inputs.get("sentiment_dispersion") or 0.0)
    sentiment_score_raw = sentiment_inputs.get("overall_score")
    if isinstance(sentiment_score_raw, (int, float)):
        sentiment_score = float(sentiment_score_raw)
        if sentiment_score > 1:
            sentiment_score = sentiment_score / 100.0
    else:
        sentiment_score = 0.5
    stage_multiplier_map = (tf_cfg.get("emotion_gate") or {}).get("stages") or {
        "高潮期": 0.5,
        "冰点期": 0.5,
        "退潮期": 0.7,
        "修复期": 0.9,
        "震荡期": 1.0,
    }
    stage_multiplier = float(stage_multiplier_map.get(stage, 1.0))
    if dispersion > 0.5:
        dispersion_multiplier = 0.7
    elif dispersion > 0.4:
        dispersion_multiplier = 0.85
    else:
        dispersion_multiplier = 1.0
    gate_multiplier = stage_multiplier * dispersion_multiplier

    flow_inputs = (runtime_inputs or {}).get("flow") if isinstance(runtime_inputs, dict) else {}
    if not isinstance(flow_inputs, dict):
        flow_inputs = {}
    ff = flow_inputs.get("fund_flow_score")
    nf = flow_inputs.get("northbound_score")
    if isinstance(ff, (int, float)) and isinstance(nf, (int, float)):
        if ff > 0 and nf > 0:
            resonance_score_global = 1.0
            resonance_type = "full_resonance"
        elif ff > 0 or nf > 0:
            resonance_score_global = 0.5
            resonance_type = "partial_resonance"
        else:
            resonance_score_global = 0.0
            resonance_type = "no_resonance"
    else:
        resonance_score_global = 0.5
        resonance_type = "market_level_fallback"
        corr_warnings.append("capital_resonance_fallback_market_level")

    m20_vals = np.array([float(x.momentum_20d) for x in rows], dtype=float) if rows else np.array([], dtype=float)
    m60_vals = np.array([float(x.momentum_60d) for x in rows], dtype=float) if rows else np.array([], dtype=float)
    vratio_vals = np.array([float(max(0.0, x.vol20_percentile)) for x in rows], dtype=float) if rows else np.array([], dtype=float)
    m20_low, m20_high = (float(m20_vals.min()), float(m20_vals.max())) if m20_vals.size else (0.0, 1.0)
    m60_low, m60_high = (float(m60_vals.min()), float(m60_vals.max())) if m60_vals.size else (0.0, 1.0)
    vr_low, vr_high = (float(vratio_vals.min()), float(vratio_vals.max())) if vratio_vals.size else (0.0, 1.0)

    three_factor_scores: Dict[str, Dict[str, Any]] = {}

    for r in rows:
        mac = r.mean_abs_corr

        if score_engine == "58":
            tech_feats = tech_features_by_sym.get(r.symbol)  # type: ignore[union-attr]
            sc, used_58 = composite_raw_score_58(
                r.momentum_20d,
                r.momentum_60d,
                r.vol_20d,
                r.max_drawdown_60d,
                r.trend_r2,
                mac,
                tech_feats,
                fac,
                use_trend=use_tr2,
                use_corr_penalty=(corr_mode == "penalize"),
            )
            if used_58 is False and tech_feats is not None:
                # Features existed but mapping fell back (should be rare).
                pass
        else:
            sc = composite_raw_score(
                r.momentum_20d,
                r.momentum_60d,
                r.vol_20d,
                r.max_drawdown_60d,
                r.trend_r2,
                mac,
                fac,
                use_trend=use_tr2,
                use_corr_penalty=(corr_mode == "penalize"),
            )
        if score_engine == "three_factor_v2":
            m20_n = _safe_norm01(r.momentum_20d, m20_low, m20_high)
            m60_n = _safe_norm01(r.momentum_60d, m60_low, m60_high)
            vr_n = _safe_norm01(max(0.0, r.vol20_percentile), vr_low, vr_high)
            momentum_score = 0.4 * m20_n + 0.3 * m60_n + 0.3 * min(vr_n / 0.5, 1.0)
            raw_score = (momentum_score * w_momentum + resonance_score_global * w_resonance)
            sc = raw_score * gate_multiplier + sentiment_score * w_sentiment
            three_factor_scores[r.symbol] = {
                "momentum_score": momentum_score,
                "capital_resonance_score": resonance_score_global,
                "capital_resonance_type": resonance_type,
                "environment_gate": gate_multiplier,
                "sentiment_score": sentiment_score,
                "raw_score": raw_score,
            }
        r.score = sc
        excl = False
        reason = None

        if use_ma and r.above_ma is not None and not r.above_ma and ma_mode == "hard":
            excl = True
            reason = "below_ma"
        if use_vg and vol_gate == "hard" and (r.vol_20d < vol_min or r.vol_20d > vol_max):
            excl = True
            reason = "vol_gate"
        if use_mdd and mdd_gate == "hard" and r.max_drawdown_60d < mdd_thr:
            excl = True
            reason = "mdd_gate"
        if corr_mode == "filter" and mac > corr_thr:
            excl = True
            reason = "high_mean_corr"
        if crowd_enabled and r.vol20_percentile >= crowd_hard_thr:
            excl = True
            reason = "crowding_hard"

        if excl:
            r.excluded = True
            r.exclude_reason = reason
            continue

        pen = 1.0
        soft: Dict[str, float] = {}
        if use_ma and ma_mode == "soft" and r.above_ma is False:
            pen *= ma_pen
            soft["ma"] = ma_pen
        if use_vg and vol_gate == "soft" and (r.vol_20d < vol_min or r.vol_20d > vol_max):
            pen *= vol_soft
            soft["vol"] = vol_soft
        if use_mdd and mdd_gate == "soft" and r.max_drawdown_60d < mdd_thr:
            pen *= mdd_soft
            soft["mdd"] = mdd_soft
        if crowd_enabled and r.vol20_percentile >= crowd_soft_thr:
            pen *= crowd_penalty
            soft["crowding"] = crowd_penalty

        r.score = sc * pen
        r.soft_penalties = soft
        working.append(r)

    if corr_mode == "filter_greedy" and corr_df is not None and len(working) >= 2:
        sorted_pre = sorted(working, key=lambda x: x.score, reverse=True)
        order = [r.symbol for r in sorted_pre]
        kept_syms = apply_correlation_filter_greedy(order, corr_df, pairwise_max)
        kept_set = set(kept_syms)
        for r in working:
            if r.symbol not in kept_set:
                r.excluded = True
                r.exclude_reason = "corr_greedy"
        working = [r for r in working if not r.excluded]

    # 分池归一化打分（M5等因子不直接以绝对量纲混比）
    def _apply_pool_norm(rows_in: List[EtfRotationRow]) -> List[EtfRotationRow]:
        pools: Dict[str, List[EtfRotationRow]] = {}
        for rr in rows_in:
            pools.setdefault(rr.pool_type, []).append(rr)
        out_rows: List[EtfRotationRow] = []
        w_m5 = float(fac.get("w_m5", 0.15))
        w_m20 = float(fac.get("w_m20", 0.30))
        w_m60 = float(fac.get("w_m60", 0.25))
        w_vol = float(fac.get("w_vol", 0.15))
        w_mdd = float(fac.get("w_mdd", 0.05))
        w_tr2 = float(fac.get("w_trend_r2", 0.10 if use_tr2 else 0.0))
        w_corr = float(fac.get("w_corr_penalty", 0.20 if corr_mode == "penalize" else 0.0))
        w_stab = float(fac.get("w_stability", 0.10))
        w_crowd = float(fac.get("w_crowding", 0.10 if crowd_enabled else 0.0))
        for _, arr in pools.items():
            m5_rank = _rank_pct({x.symbol: x.momentum_5d for x in arr}, reverse=True)
            m20_rank = _rank_pct({x.symbol: x.momentum_20d for x in arr}, reverse=True)
            m60_rank = _rank_pct({x.symbol: x.momentum_60d for x in arr}, reverse=True)
            vol_rank = _rank_pct({x.symbol: x.vol_20d for x in arr}, reverse=False)
            mdd_rank = _rank_pct({x.symbol: x.max_drawdown_60d for x in arr}, reverse=True)
            tr2_rank = _rank_pct({x.symbol: x.trend_r2 for x in arr}, reverse=True)
            corr_rank = _rank_pct({x.symbol: x.mean_abs_corr for x in arr}, reverse=False)
            crowd_rank = _rank_pct({x.symbol: x.vol20_percentile for x in arr}, reverse=False)
            stab_rank = _rank_pct({x.symbol: x.stability_score for x in arr}, reverse=True)
            for r in arr:
                norm_score = (
                    w_m5 * m5_rank.get(r.symbol, 0.5)
                    + w_m20 * m20_rank.get(r.symbol, 0.5)
                    + w_m60 * m60_rank.get(r.symbol, 0.5)
                    + w_vol * vol_rank.get(r.symbol, 0.5)
                    + w_mdd * mdd_rank.get(r.symbol, 0.5)
                    + w_tr2 * tr2_rank.get(r.symbol, 0.5)
                    + w_stab * stab_rank.get(r.symbol, 0.5)
                    + w_corr * corr_rank.get(r.symbol, 0.5)
                    + w_crowd * crowd_rank.get(r.symbol, 0.5)
                )
                if r.soft_penalties:
                    p = 1.0
                    for pv in r.soft_penalties.values():
                        p *= float(pv)
                    r.score = float(norm_score) * p
                else:
                    r.score = float(norm_score)
                out_rows.append(r)
        return out_rows

    working = _apply_pool_norm(working)
    ranked = sorted(working, key=lambda x: x.score, reverse=True)
    fallback_legacy = False
    allow_legacy_fallback = bool(de_cfg.get("fallback_legacy_ranking", False))
    if allow_legacy_fallback and (not ranked) and rows:
        fallback_legacy = True
        ranked = sorted(rows, key=lambda x: x.legacy_score, reverse=True)

    inactive = [r for r in rows if r.excluded]
    ranked_by_pool: Dict[str, List[EtfRotationRow]] = {}
    for rr in ranked:
        ranked_by_pool.setdefault(rr.pool_type, []).append(rr)

    industry_total = sum(1 for s in symbols if pool_type_map.get(s) == "industry")
    concept_total = sum(1 for s in symbols if pool_type_map.get(s) == "concept")
    industry_ok = sum(1 for r in rows if r.pool_type == "industry" and not r.excluded)
    concept_ok = sum(1 for r in rows if r.pool_type == "concept" and not r.excluded)
    overall_ok = sum(1 for r in rows if not r.excluded)
    # 注意：0 是合法值（用于显式关闭覆盖阈值），不能用 `or` 回退。
    ind_min = int(de_cfg.get("industry_min_available", 5))
    con_min = int(de_cfg.get("concept_min_available", 5))
    # 仅对“实际存在的分池”做覆盖率阈值校验；避免显式传入自定义池时 concept_total=0 仍触发降级。
    degraded = False
    if industry_total > 0 and industry_ok < ind_min:
        degraded = True
    if concept_total > 0 and concept_ok < con_min:
        degraded = True
    # 当本次池不属于 industry/concept（两者 total 均为 0）时，兜底为“是否至少有可用标的”
    if industry_total == 0 and concept_total == 0 and overall_ok == 0:
        degraded = True
    degraded_reasons: List[str] = []
    if industry_total > 0 and industry_ok < ind_min:
        degraded_reasons.append(f"industry_available={industry_ok}<{ind_min}")
    if concept_total > 0 and concept_ok < con_min:
        degraded_reasons.append(f"concept_available={concept_ok}<{con_min}")
    if industry_total == 0 and concept_total == 0 and overall_ok == 0:
        degraded_reasons.append("no_available_symbols_in_custom_pool")

    structured_warnings = build_structured_rotation_warnings(
        errors=errors,
        corr_warnings=list(corr_warnings),
        min_history_days=min_rows,
        correlation_lookback_config=corr_lb,
    )

    return {
        "ranked_active": ranked,
        "ranked_by_pool": ranked_by_pool,
        "ranked_all_for_display": sorted(rows, key=lambda x: x.legacy_score, reverse=True),
        "inactive": inactive,
        "fallback_legacy_ranking": fallback_legacy,
        "correlation_matrix": (
            corr_df.fillna(0.0).round(4).to_dict() if corr_df is not None else None
        ),
        "correlation_symbols": list(corr_df.index) if corr_df is not None else [],
        "warnings": corr_warnings,
        "structured_warnings": structured_warnings,
        "config_snapshot": {
            "data_need": data_need,
            "load_range": [start_d, end_d],
            "correlation_mode": corr_mode,
        },
        "data_readiness": {
            "load_health": load_health,
            "industry_coverage": {"available": industry_ok, "total": industry_total},
            "concept_coverage": {"available": concept_ok, "total": concept_total},
            "degraded": degraded,
            "degraded_reasons": degraded_reasons,
            "degraded_evidence": [
                {
                    "symbol": k,
                    "pool_type": pool_type_map.get(k, "unknown"),
                    "failure_sources": [v.get("source")],
                    "attempted_fallback_sources": v.get("attempted_fallback_sources") or [],
                    "retry_policy": v.get("retry_policy") or {},
                    "final_degraded": not bool(v.get("ok")),
                    "reason": v.get("message"),
                }
                for k, v in load_health.items()
                if not bool(v.get("ok"))
            ],
            "correlation_warnings": corr_warnings,
        },
        "pool_type_map": pool_type_map,
        "errors": errors,
        "tech_features_by_symbol": tech_features_by_sym if score_engine == "58" else None,
        "three_factor_context": {
            "enabled": score_engine == "three_factor_v2",
            "weights": {
                "sector_momentum": w_momentum,
                "capital_resonance": w_resonance,
                "sentiment": w_sentiment,
            },
            "sentiment": {
                "stage": stage,
                "dispersion": dispersion,
                "score": sentiment_score,
            },
            "gate": {
                "stage_multiplier": stage_multiplier,
                "dispersion_multiplier": dispersion_multiplier,
                "total_multiplier": gate_multiplier,
            },
            "capital_resonance": {
                "score": resonance_score_global,
                "type": resonance_type,
                "fund_flow_score": ff,
                "northbound_score": nf,
            },
            "by_symbol": three_factor_scores if score_engine == "three_factor_v2" else {},
        },
    }


def pool_hash(symbols: List[str]) -> str:
    raw = ",".join(symbols)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def append_rotation_history(
    *,
    top_symbols: List[str],
    top_k: int,
    pool_syms: List[str],
    ranked_symbols: Optional[List[str]] = None,
    config: Dict[str, Any],
) -> None:
    paths = config.get("paths") or {}
    rel = paths.get("history_jsonl") or "data/etf_rotation_runs.jsonl"
    path = _project_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "top_k": top_k,
        "top_symbols": top_symbols,
        "pool_hash": pool_hash(pool_syms),
        "ranked_symbols": list(ranked_symbols or top_symbols),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_last_rotation_runs(n: int = 3, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    cfg = config or load_rotation_config()
    paths = cfg.get("paths") or {}
    rel = paths.get("history_jsonl") or "data/etf_rotation_runs.jsonl"
    path = _project_root() / rel
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    out: List[Dict[str, Any]] = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


__all__ = [
    "EtfRotationRow",
    "resolve_etf_pool",
    "resolve_pool_type_map",
    "compute_data_need",
    "compute_stability_scores",
    "run_rotation_pipeline",
    "load_rotation_config",
    "load_etf_daily_df",
    "default_load_date_range",
    "trim_dataframe",
    "pool_hash",
    "append_rotation_history",
    "read_last_rotation_runs",
]
