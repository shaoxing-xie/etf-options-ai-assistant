"""
ETF 轮动：指标、相关性、评分与过滤（供研究与回测共用）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.rotation_config_loader import load_rotation_config


@dataclass
class EtfRotationRow:
    symbol: str
    momentum_20d: float
    momentum_60d: float
    vol_20d: float
    max_drawdown_60d: float
    trend_r2: float
    mean_abs_corr: float
    above_ma: Optional[bool]
    legacy_score: float
    score: float
    excluded: bool = False
    exclude_reason: Optional[str] = None
    soft_penalties: Dict[str, float] = field(default_factory=dict)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_etf_pool(etf_pool: Optional[str], config: Dict[str, Any]) -> List[str]:
    """非空 etf_pool 优先；否则 symbols.json 分组并集 + extra。"""
    if etf_pool is not None and str(etf_pool).strip():
        return [s.strip() for s in str(etf_pool).split(",") if s.strip()]

    from src.symbols_loader import load_symbols_config

    pool_cfg = config.get("pool") or {}
    groups = pool_cfg.get("symbol_groups") or ["core", "industry_etf"]
    extras = pool_cfg.get("extra_etf_codes") or []
    sym_cfg = load_symbols_config()
    codes: List[str] = []
    for gname in groups:
        g = sym_cfg.get(gname)
        if g:
            codes.extend(list(g.etf_codes or []))
    codes.extend(str(x) for x in extras)
    seen: set[str] = set()
    out: List[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return sorted(out)


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


def compute_base_metrics(s: pd.Series, symbol: str, min_rows: int) -> Tuple[float, float, float, float]:
    if len(s) < min_rows:
        raise ValueError(f"{symbol}: insufficient rows ({len(s)} < {min_rows})")
    m20 = float(s.iloc[-1] / s.iloc[-21] - 1.0)
    m60 = float(s.iloc[-1] / s.iloc[-61] - 1.0)
    rets = s.pct_change().dropna()
    vol20 = float(rets.iloc[-20:].std(ddof=0) * np.sqrt(252))
    window = s.iloc[-60:]
    roll_max = window.cummax()
    dd = (window / roll_max) - 1.0
    mdd60 = float(dd.min())
    return m20, m60, vol20, mdd60


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
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    读取 ETF 日线；缓存部分命中时仍返回已有 DataFrame（与研究/回测一致）。
    """
    from data_access.read_cache_data import read_cache_data

    out = read_cache_data(
        data_type="etf_daily",
        symbol=symbol,
        start_date=start_yyyymmdd,
        end_date=end_yyyymmdd,
        return_df=True,
    )
    if out.get("success"):
        return out.get("df"), None
    df = out.get("df")
    if df is not None and not (hasattr(df, "empty") and df.empty):
        return df, out.get("message") or "partial_cache"
    return None, out.get("message")


def default_load_date_range(
    *,
    as_of_yyyymmdd: Optional[str] = None,
    calendar_days_back: int = 2200,
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
    """
    warnings: List[str] = []
    if len(close_by_symbol) < 2:
        return None, warnings

    syms = list(close_by_symbol.keys())
    all_dt = all(isinstance(close_by_symbol[s].index, pd.DatetimeIndex) for s in syms)

    if all_dt:
        common_idx = close_by_symbol[syms[0]].index
        for s in syms[1:]:
            common_idx = common_idx.intersection(close_by_symbol[s].index)
        if len(common_idx) < max(lookback + 2, 10):
            warnings.append("aligned_trading_days_insufficient_for_correlation")
            return None, warnings
        aligned = {s: close_by_symbol[s].reindex(common_idx).dropna() for s in syms}
        min_len = min(len(v) for v in aligned.values())
        if min_len < lookback + 2:
            return None, warnings + ["short_history_after_align"]
    else:
        min_len = min(len(close_by_symbol[s]) for s in syms)
        if min_len < lookback + 2:
            warnings.append("positional_align_too_short")
            return None, warnings
        aligned = {s: close_by_symbol[s].iloc[-min_len:].reset_index(drop=True) for s in syms}

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


def run_rotation_pipeline(
    symbols: List[str],
    config: Dict[str, Any],
    *,
    lookback_days: int = 120,
    as_of_yyyymmdd: Optional[str] = None,
) -> Dict[str, Any]:
    """
    加载日线、计算指标、相关性与最终排名。
    """
    feats = config.get("features") or {}
    fcfg = config.get("filters") or {}
    fac = config.get("factors") or {}
    leg_fac = config.get("legacy_factors") or {}

    data_need = compute_data_need(config, lookback_days)
    start_d, end_d = default_load_date_range(as_of_yyyymmdd=as_of_yyyymmdd)

    rows: List[EtfRotationRow] = []
    errors: List[str] = []
    close_by_symbol: Dict[str, pd.Series] = {}
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

    use_corr = bool(feats.get("use_correlation", True)) and corr_mode != "off"
    use_ma = bool(feats.get("use_ma", True)) and ma_mode != "off"
    use_tr2 = bool(feats.get("use_trend_r2", True))
    use_vg = bool(feats.get("use_vol_gate", False)) or vol_gate != "off"
    use_mdd = bool(feats.get("use_mdd_gate", False)) or mdd_gate != "off"

    for sym in symbols:
        df, msg = load_etf_daily_df(sym, start_yyyymmdd=start_d, end_yyyymmdd=end_d)
        if df is None or df.empty:
            errors.append(f"{sym}: load failed: {msg}")
            continue
        df = trim_dataframe(df, lookback_days, data_need)
        try:
            s, _ = extract_close_series(df)
            if isinstance(s.index, pd.DatetimeIndex):
                close_by_symbol[sym] = s
            else:
                close_by_symbol[sym] = s
            m20, m60, vol20, mdd60 = compute_base_metrics(s, sym, min_rows)
            trend_r2 = _trend_r2_log(s, tr_w) if use_tr2 else 0.0
            above_ma = compute_ma_above(s, ma_period) if use_ma else None
            leg_score = _legacy_score(m20, m60, vol20, mdd60, leg_fac)
            rows.append(
                EtfRotationRow(
                    symbol=sym,
                    momentum_20d=m20,
                    momentum_60d=m60,
                    vol_20d=vol20,
                    max_drawdown_60d=mdd60,
                    trend_r2=trend_r2,
                    mean_abs_corr=0.0,
                    above_ma=above_ma,
                    legacy_score=leg_score,
                    score=0.0,
                )
            )
        except Exception as e:
            errors.append(f"{sym}: {e}")

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

    for r in rows:
        r.mean_abs_corr = float(mean_abs_map.get(r.symbol, 0.0))

    working: List[EtfRotationRow] = []
    for r in rows:
        mac = r.mean_abs_corr
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

    ranked = sorted(working, key=lambda x: x.score, reverse=True)
    fallback_legacy = False
    if not ranked and rows:
        fallback_legacy = True
        ranked = sorted(rows, key=lambda x: x.legacy_score, reverse=True)

    inactive = [r for r in rows if r.excluded]

    return {
        "ranked_active": ranked,
        "ranked_all_for_display": sorted(rows, key=lambda x: x.legacy_score, reverse=True),
        "inactive": inactive,
        "fallback_legacy_ranking": fallback_legacy,
        "correlation_matrix": (
            corr_df.fillna(0.0).round(4).to_dict() if corr_df is not None else None
        ),
        "correlation_symbols": list(corr_df.index) if corr_df is not None else [],
        "warnings": corr_warnings,
        "config_snapshot": {
            "data_need": data_need,
            "load_range": [start_d, end_d],
            "correlation_mode": corr_mode,
        },
        "errors": errors,
    }


def pool_hash(symbols: List[str]) -> str:
    raw = ",".join(symbols)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def append_rotation_history(
    *,
    top_symbols: List[str],
    top_k: int,
    pool_syms: List[str],
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
    "compute_data_need",
    "run_rotation_pipeline",
    "load_rotation_config",
    "load_etf_daily_df",
    "default_load_date_range",
    "trim_dataframe",
    "pool_hash",
    "append_rotation_history",
    "read_last_rotation_runs",
]
