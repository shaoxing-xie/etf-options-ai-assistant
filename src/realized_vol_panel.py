"""
多窗口已实现波动率（realized vol）与可选波动率锥。

与历史波动率口径一致（见计划「IV 口径 / 年化」）：
- 日收益：收盘价 pct_change，dropna 后取最近 w 期；
- 样本标准差（pandas 默认 ddof=1）；
- 日线年化：std * sqrt(252) * 100，单位 %；
- 上限 500%%，负值置 0。

波动率锥：对每个窗口 w，在完整样本上计算 rolling 年化 HV 序列，
输出 min/max/mean 及当前值在序列中的经验分位（ties: 平均秩思路，用 mean(hist <= current)*100）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

MAX_VOLATILITY_THRESHOLD = 500.0


def _annualize_from_std(std: float, data_period: str = "day") -> float:
    """从收益率标准差得到年化波动率 %%。"""
    if std is None or (isinstance(std, float) and np.isnan(std)):
        return float("nan")
    s = float(std)
    if data_period == "minute":
        ann = s * np.sqrt(240 * 252) * 100
    else:
        ann = s * np.sqrt(252) * 100
    if ann > MAX_VOLATILITY_THRESHOLD:
        ann = MAX_VOLATILITY_THRESHOLD
    if ann < 0:
        ann = 0.0
    return ann


def _single_window_hv_pct(returns: pd.Series, window: int, data_period: str = "day") -> Optional[float]:
    """returns 为已 dropna 的日收益率序列，取尾部 window 条。"""
    if returns is None or len(returns) < window or window < 1:
        return None
    recent = returns.tail(window)
    std = recent.std()
    ann = _annualize_from_std(std, data_period)
    if ann is None or (isinstance(ann, float) and np.isnan(ann)):
        return None
    return float(ann)


def realized_vol_windows(
    df: pd.DataFrame,
    windows: List[int],
    close_col: str = "收盘",
    data_period: str = "day",
) -> Dict[str, Optional[float]]:
    """
    多窗口年化已实现波动率（%%）。

    Returns:
        键为 str(window)，样本不足时为 None。
    """
    out: Dict[str, Optional[float]] = {}
    if df is None or getattr(df, "empty", True) or close_col not in df.columns:
        for w in windows:
            out[str(int(w))] = None
        return out
    returns = df[close_col].pct_change().dropna()
    for w in windows:
        wi = int(w)
        out[str(wi)] = _single_window_hv_pct(returns, wi, data_period)
    return out


def rolling_hv_series(
    df: pd.DataFrame,
    window: int,
    close_col: str = "收盘",
    data_period: str = "day",
) -> pd.Series:
    """
    与单点 HV 同口径的 rolling 年化序列（索引与 returns 对齐，前 window-1 为 NaN）。
    """
    if df is None or getattr(df, "empty", True) or close_col not in df.columns:
        return pd.Series(dtype=float)
    px = df[close_col].astype(float)
    rets = px.pct_change()
    roll_std = rets.rolling(window=window, min_periods=window).std()
    ann = roll_std * np.sqrt(252) * 100 if data_period != "minute" else roll_std * np.sqrt(240 * 252) * 100
    ann = ann.clip(lower=0.0, upper=MAX_VOLATILITY_THRESHOLD)
    return ann


def volatility_cone_for_windows(
    df: pd.DataFrame,
    windows: List[int],
    close_col: str = "收盘",
    data_period: str = "day",
    min_history_points: int = 60,
) -> Dict[str, Any]:
    """
    对每个窗口计算波动率锥统计。

    Returns:
        { "20": {"min", "max", "mean", "percentile", "current"} | {"reason": str} }
    """
    result: Dict[str, Any] = {}
    if df is None or getattr(df, "empty", True) or close_col not in df.columns:
        for w in windows:
            result[str(int(w))] = {"reason": "no_data"}
        return result

    for w in windows:
        wi = int(w)
        key = str(wi)
        series = rolling_hv_series(df, wi, close_col, data_period).dropna()
        if len(series) < min_history_points:
            result[key] = {"reason": f"insufficient_history_need_{min_history_points}_got_{len(series)}"}
            continue
        hist = series.values.astype(float)
        current = float(hist[-1])
        past = hist[:-1]
        if len(past) == 0:
            result[key] = {"reason": "no_past_distribution"}
            continue
        pct = float(np.mean(past <= current) * 100.0)
        result[key] = {
            "min": float(np.min(hist)),
            "max": float(np.max(hist)),
            "mean": float(np.mean(hist)),
            "percentile": pct,
            "current": current,
        }
    return result


def merge_historical_snapshot_config(base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """合并 historical_snapshot 配置（defaults + load_system_config）。"""
    defaults: Dict[str, Any] = {
        "enabled": True,
        "default_windows": [5, 10, 20, 60, 252],
        "max_symbols": 20,
        "cone_history_calendar_days": 756,
        "include_vol_cone_default": False,
        "include_iv_default": False,
        "iv": {
            "sse_only": True,
            "near_month_min_days": 7,
            "atm_method": "average_call_put",
            "eq_30d_enabled": True,
        },
    }
    cfg = dict(defaults)
    if base is None:
        try:
            from src.config_loader import load_system_config

            base = load_system_config()
        except Exception:
            base = {}
    hs = base.get("historical_snapshot") if isinstance(base, dict) else None
    if isinstance(hs, dict):
        for k, v in hs.items():
            if k == "iv" and isinstance(v, dict) and isinstance(cfg.get("iv"), dict):
                merged_iv = dict(cfg["iv"])
                merged_iv.update(v)
                cfg["iv"] = merged_iv
            elif k != "iv":
                cfg[k] = v
    return cfg
