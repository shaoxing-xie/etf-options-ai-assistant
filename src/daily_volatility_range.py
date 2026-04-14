"""
日频全日波动区间：多窗口日收益率波动（默认 5/22/63）+ ATR(14) 融合；
交易时段可选分钟/开盘位置有界纠偏。不含期权合约。
"""

from __future__ import annotations

import math
from datetime import datetime, time as dt_time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz

from src.logger_config import get_module_logger
from src.config_loader import load_system_config
from src.indicator_calculator import calculate_atr, calculate_historical_volatility
from src.volatility_range import get_remaining_trading_time

logger = get_module_logger(__name__)

DEFAULT_CFG: Dict[str, Any] = {
    "enabled": True,
    "horizon": "1d",
    "target_session": "current",
    "windows": [5, 22, 63],
    "hv_weights": [0.25, 0.35, 0.40],
    "atr_period": 14,
    "atr_weight": 0.20,
    "parkinson_enabled": False,
    "min_data_days": 120,
    "fetch_lookback_days": 600,
    "range_multiplier": 2.2,
    "anchor_price": {"mode": "auto"},
    "intraday_adjustment": {
        "enabled": True,
        "minute_lookback": 30,
        "max_adjust_pct": 0.8,
    },
    "range_clamp": {"min_range_pct": 1.0, "max_range_pct": 12.0},
}


def _merge_cfg(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = dict(DEFAULT_CFG)
    if not config:
        return base
    user = config.get("daily_volatility_range") or {}
    if isinstance(user, dict):
        base.update({k: v for k, v in user.items() if v is not None})
        if isinstance(user.get("intraday_adjustment"), dict):
            base["intraday_adjustment"] = {
                **DEFAULT_CFG["intraday_adjustment"],
                **user["intraday_adjustment"],
            }
        if isinstance(user.get("range_clamp"), dict):
            base["range_clamp"] = {**DEFAULT_CFG["range_clamp"], **user["range_clamp"]}
        if isinstance(user.get("anchor_price"), dict):
            base["anchor_price"] = {**DEFAULT_CFG["anchor_price"], **user["anchor_price"]}
    return base


def _is_in_continuous_trading_session(cfg: Dict[str, Any]) -> bool:
    """是否处于连续竞价时段（上午或下午盘）。"""
    try:
        from src.volatility_range import get_trading_hours_config

        th = get_trading_hours_config(cfg)
        tz = pytz.timezone(th.get("timezone", "Asia/Shanghai"))
        now = datetime.now(tz).time()
        ms = dt_time.fromisoformat(th.get("morning_start", "09:30"))
        me = dt_time.fromisoformat(th.get("morning_end", "11:30"))
        as_ = dt_time.fromisoformat(th.get("afternoon_start", "13:00"))
        ae = dt_time.fromisoformat(th.get("afternoon_end", "15:00"))
        return (ms <= now <= me) or (as_ <= now <= ae)
    except Exception as e:
        logger.debug("交易时段判断失败，按非盘中处理: %s", e)
        return False


def _normalize_ohlc_df(df: pd.DataFrame) -> Tuple[pd.DataFrame, str, Optional[str], Optional[str]]:
    """统一出 收盘/最高/最低 列名。"""
    if df is None or df.empty:
        raise ValueError("empty dataframe")

    close_col = None
    for c in ("收盘", "close", "收盘价", "CLOSE", "Close"):
        if c in df.columns:
            close_col = c
            break
    if close_col is None:
        raise ValueError("no close column")

    high_col = None
    for c in ("最高", "high", "最高价", "HIGH", "High"):
        if c in df.columns:
            high_col = c
            break
    low_col = None
    for c in ("最低", "low", "最低价", "LOW", "Low"):
        if c in df.columns:
            low_col = c
            break

    out = df.copy()
    for c in (close_col, high_col, low_col):
        if c and c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=[close_col])
    for date_col in ("日期", "date", "Date"):
        if date_col in out.columns:
            out = out.sort_values(date_col).reset_index(drop=True)
            break
    return out, close_col, high_col, low_col


def _fetch_daily_bars(
    symbol: str,
    asset_type: str,
    start_ymd: str,
    end_ymd: str,
) -> Optional[pd.DataFrame]:
    from src.data_collector import fetch_etf_daily_em, fetch_index_daily_em, fetch_stock_daily_hist

    if asset_type == "etf":
        return fetch_etf_daily_em(symbol=symbol, period="daily", start_date=start_ymd, end_date=end_ymd)
    if asset_type == "index":
        return fetch_index_daily_em(symbol=symbol, period="daily", start_date=start_ymd, end_date=end_ymd)
    if asset_type == "stock":
        return fetch_stock_daily_hist(symbol, start_ymd, end_ymd)
    return None


def _resolve_anchor_price(
    symbol: str,
    asset_type: str,
    daily_df: pd.DataFrame,
    close_col: str,
    cfg: Dict[str, Any],
) -> float:
    mode = (cfg.get("anchor_price") or {}).get("mode", "auto")
    last_close = float(daily_df[close_col].iloc[-1])

    if mode == "last_close":
        return last_close

    spot: Optional[float] = None
    try:
        if asset_type == "etf":
            from src.data_collector import get_etf_current_price

            spot = get_etf_current_price(symbol)
        elif asset_type == "index":
            from src.data_collector import get_index_current_price

            spot = get_index_current_price(symbol)
        elif asset_type == "stock":
            from src.data_collector import get_stock_current_price

            spot = get_stock_current_price(symbol)
    except Exception as e:
        logger.debug("现价获取失败，回退昨收: %s", e)

    if spot is not None and spot > 0:
        return float(spot)
    return last_close


def _parkinson_mean_range_pct(
    df: pd.DataFrame,
    high_col: str,
    low_col: str,
    close_col: str,
    lookback: int = 22,
) -> Optional[float]:
    if not high_col or not low_col:
        return None
    seg = df.tail(lookback)
    if len(seg) < 5:
        return None
    ratios = []
    for _, row in seg.iterrows():
        h, l_, c = row.get(high_col), row.get(low_col), row.get(close_col)
        try:
            h, l_, c = float(h), float(l_), float(c)
            if c > 0 and h > 0 and l_ > 0 and h >= l_:
                ratios.append((h - l_) / c * 100.0)
        except (TypeError, ValueError):
            continue
    if not ratios:
        return None
    return float(np.mean(ratios))


def _intraday_adjust_range_pct(
    base_range_pct: float,
    symbol: str,
    asset_type: str,
    anchor: float,
    adj_cfg: Dict[str, Any],
    system_config: Dict[str, Any],
) -> Tuple[float, bool, str]:
    if not adj_cfg.get("enabled", True):
        return base_range_pct, False, ""
    if not _is_in_continuous_trading_session(system_config):
        return base_range_pct, False, ""

    lookback = int(adj_cfg.get("minute_lookback", 30))
    max_adj = float(adj_cfg.get("max_adjust_pct", 0.8))

    try:
        if asset_type == "etf":
            from src.data_collector import fetch_etf_minute_data_with_fallback

            m30, m15 = fetch_etf_minute_data_with_fallback(
                underlying=symbol, lookback_days=2, max_retries=1, retry_delay=0.5
            )
            minute_df = m15 if m15 is not None and not m15.empty else m30
        elif asset_type == "stock":
            from src.data_collector import fetch_stock_minute_data_with_fallback

            m30, m15 = fetch_stock_minute_data_with_fallback(
                symbol=symbol, lookback_days=2, max_retries=1, retry_delay=0.5
            )
            minute_df = m15 if m15 is not None and not m15.empty else m30
        else:
            from src.data_collector import fetch_index_minute_data_with_fallback

            m30, m15 = fetch_index_minute_data_with_fallback(
                symbol=symbol, lookback_days=2, max_retries=1, retry_delay=0.5
            )
            minute_df = m15 if m15 is not None and not m15.empty else m30
    except Exception as e:
        logger.debug("分钟数据用于纠偏失败: %s", e)
        return base_range_pct, False, ""

    if minute_df is None or minute_df.empty:
        return base_range_pct, False, ""

    px_col = "收盘" if "收盘" in minute_df.columns else ("close" if "close" in minute_df.columns else None)
    if not px_col:
        return base_range_pct, False, ""

    tail = minute_df.tail(max(lookback, 5))
    chg = pd.to_numeric(tail[px_col], errors="coerce").pct_change().dropna()
    if chg.empty:
        return base_range_pct, False, ""

    minute_sigma = float(chg.std())
    # 与「日频 std」可比：短窗分钟波动放大到日尺度粗近似
    scale = math.sqrt(240.0 / max(len(chg), 1))
    bump = min(max_adj, minute_sigma * scale * 100.0 * 0.5)

    open_px = float(pd.to_numeric(tail[px_col], errors="coerce").iloc[0])
    if open_px > 0:
        rel = abs(anchor / open_px - 1.0) * 100.0
        bump += min(max_adj * 0.5, rel * 0.15)

    out = min(base_range_pct + bump, base_range_pct + max_adj)
    return out, True, f"盘中纠偏(+{bump:.2f}% 量级内)"


def compute_daily_volatility_range(
    symbol: str,
    asset_type: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    计算标的「全日」波动区间（指数/ETF/股票）。

    Returns:
        成功: success True + upper/lower/range_pct/...
        失败: success False + data.error_code
    """
    system_config = config if config is not None else load_system_config(use_cache=True)
    cfg = _merge_cfg(system_config)

    if not cfg.get("enabled", True):
        return {
            "success": False,
            "message": "日频波动区间工具已在配置中关闭 (daily_volatility_range.enabled=false)",
            "data": {"error_code": "DAILY_RANGE_DISABLED", "symbol": symbol, "asset_type": asset_type},
        }

    windows: List[int] = list(cfg.get("windows") or [5, 22, 63])
    hv_weights: List[float] = [float(x) for x in (cfg.get("hv_weights") or [0.25, 0.35, 0.40])]
    if len(hv_weights) != len(windows):
        return {
            "success": False,
            "message": "hv_weights 与 windows 长度不一致",
            "data": {"error_code": "DAILY_RANGE_CONFIG_INVALID", "symbol": symbol},
        }

    min_days = int(cfg.get("min_data_days", 120))
    fetch_cal_days = int(cfg.get("fetch_lookback_days", 600))
    tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(tz)
    end_ymd = now.strftime("%Y%m%d")
    start_ymd = (now - pd.Timedelta(days=fetch_cal_days)).strftime("%Y%m%d")

    raw = _fetch_daily_bars(symbol, asset_type, start_ymd, end_ymd)
    if raw is None or raw.empty:
        return {
            "success": False,
            "message": f"无法获取 {symbol} 日K 数据",
            "data": {"error_code": "DAILY_HISTORY_UNAVAILABLE", "symbol": symbol, "asset_type": asset_type},
        }

    try:
        df, close_col, high_col, low_col = _normalize_ohlc_df(raw)
    except ValueError as e:
        return {
            "success": False,
            "message": str(e),
            "data": {"error_code": "DAILY_HISTORY_INVALID", "symbol": symbol},
        }

    mw = max(windows)
    atr_p = int(cfg.get("atr_period", 14))
    floor_rows = int(cfg.get("min_data_days_floor", 45))
    min_rows_hard = max(mw + 5, atr_p + 5, floor_rows)
    soft_fb = bool(cfg.get("min_data_days_soft_fallback", False))
    history_warning: Optional[str] = None

    if len(df) < min_days:
        if soft_fb and len(df) >= min_rows_hard:
            history_warning = (
                f"日K 仅 {len(df)} 根，低于 min_data_days={min_days}，"
                f"已按软降级规则继续计算（置信度下调；建议检查标的是否新上市或数据源是否截断）"
            )
            logger.warning("compute_daily_volatility_range: %s (%s)", history_warning, symbol)
        else:
            return {
                "success": False,
                "message": (
                    f"日K 不足 {min_days} 根（当前 {len(df)}），拒绝输出。"
                    f"若历史实际可用但条数不足，可在 config daily_volatility_range 中设置 "
                    f"min_data_days_soft_fallback: true 并酌情降低 min_data_days 或检查数据源。"
                ),
                "data": {
                    "error_code": "DAILY_HISTORY_INSUFFICIENT",
                    "symbol": symbol,
                    "rows": len(df),
                    "required": min_days,
                    "min_rows_for_soft": min_rows_hard,
                },
            }

    if len(df) < mw + 5 or len(df) < atr_p + 5:
        return {
            "success": False,
            "message": f"日K 长度不足以计算 max(window)={mw} 或 ATR({atr_p})",
            "data": {"error_code": "DAILY_HISTORY_INSUFFICIENT", "symbol": symbol, "rows": len(df)},
        }

    daily_sigma_pcts: List[float] = []
    ann_vols: List[Optional[float]] = []
    for w in windows:
        ann = calculate_historical_volatility(df, period=w, close_col=close_col, data_period="day")
        if ann is None or ann <= 0:
            return {
                "success": False,
                "message": f"窗口 {w} 日历史波动率计算失败",
                "data": {"error_code": "DAILY_HV_CALC_FAILED", "symbol": symbol, "window": w},
            }
        ann_vols.append(float(ann))
        # 日收益率标准差（百分比点）：年化% / sqrt(252)
        daily_sigma_pcts.append(float(ann) / math.sqrt(252.0))

    atr_weight = float(cfg.get("atr_weight", 0.20))
    atr_series = None
    atr_pct = 0.0
    if high_col and low_col:
        atr_series = calculate_atr(df, period=atr_p, high_col=high_col, low_col=low_col, close_col=close_col)
    if atr_series is not None and not atr_series.empty:
        atr_val = float(atr_series.iloc[-1])
        # 先占位，锚价后再算 atr_pct
        _atr_val = atr_val
    else:
        _atr_val = None

    anchor = _resolve_anchor_price(symbol, asset_type, df, close_col, cfg)
    if anchor <= 0:
        return {
            "success": False,
            "message": "锚定价格无效",
            "data": {"error_code": "DAILY_ANCHOR_INVALID", "symbol": symbol},
        }

    if _atr_val is not None and _atr_val > 0:
        atr_pct = _atr_val / anchor * 100.0

    park_pct: Optional[float] = None
    if cfg.get("parkinson_enabled") and high_col and low_col:
        park_pct = _parkinson_mean_range_pct(df, high_col, low_col, close_col, lookback=22)
        if park_pct is not None and atr_pct > 0:
            atr_pct = (atr_pct + park_pct) / 2.0
        elif park_pct is not None:
            atr_pct = park_pct

    w_atr_use = float(atr_weight) if atr_pct > 0 else 0.0
    w_sum = sum(abs(w) for w in hv_weights) + abs(w_atr_use)
    if w_sum <= 0:
        w_sum = 1.0

    blended = sum((hv_weights[i] / w_sum) * daily_sigma_pcts[i] for i in range(len(windows))) + (
        w_atr_use / w_sum
    ) * atr_pct

    mult = float(cfg.get("range_multiplier", 2.2))
    range_pct = mult * blended

    rc = cfg.get("range_clamp") or {}
    rmin = float(rc.get("min_range_pct", 1.0))
    rmax = float(rc.get("max_range_pct", 12.0))
    range_pct = max(rmin, min(rmax, range_pct))

    intraday_adjusted = False
    adj_note = ""
    adj_cfg = cfg.get("intraday_adjustment") or {}
    range_pct, intraday_adjusted, adj_note = _intraday_adjust_range_pct(
        range_pct, symbol, asset_type, anchor, adj_cfg, system_config
    )
    range_pct = max(rmin, min(rmax, range_pct))

    half = anchor * (range_pct / 200.0)
    lower = max(0.0, anchor - half)
    upper = anchor + half

    remaining = int(get_remaining_trading_time(system_config))
    conf = float(min(0.65, 0.45 + 0.001 * len(df)))
    if intraday_adjusted:
        conf = min(0.65, conf + 0.03)
    if history_warning:
        conf = max(0.22, min(0.55, conf - 0.18))

    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    method_parts = [
        f"日频多窗口HV({','.join(map(str, windows))})+ATR{atr_p}",
    ]
    if cfg.get("parkinson_enabled"):
        method_parts.append("Parkinson均值")
    if intraday_adjusted:
        method_parts.append("盘中纠偏")

    return {
        "success": True,
        "message": "日频全日波动区间计算完成",
        "data": {
            "symbol": symbol,
            "asset_type": asset_type,
            "current_price": anchor,
            "upper": upper,
            "lower": lower,
            "range_pct": round(range_pct, 4),
            "confidence": round(conf, 4),
            "method": " / ".join(method_parts),
            "timestamp": ts,
            "horizon": cfg.get("horizon", "1d"),
            "target_session": cfg.get("target_session", "current"),
            "windows_used": list(windows),
            "hv_annualized_pct": [round(x, 4) for x in ann_vols],
            "atr_pct_contribution": round(atr_pct, 4),
            "weights_effective": {
                "hv": [round(w / w_sum, 4) for w in hv_weights],
                "atr": round(w_atr_use / w_sum, 4),
            },
            "intraday_adjusted": intraday_adjusted,
            "intraday_adjust_note": adj_note,
            "remaining_trading_minutes_snapshot": remaining,
            "history_warning": history_warning,
        },
    }
