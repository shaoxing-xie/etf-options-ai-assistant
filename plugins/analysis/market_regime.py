from __future__ import annotations

from typing import Any, Dict


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def tool_detect_market_regime(
    *,
    symbol: str = "510300",
    mode: str = "prod",
) -> Dict[str, Any]:
    """
    OpenClaw 工具：市场状态识别（Market Regime，研究级）

    目标：
    - 用尽可能低耦合的规则/特征，给出一个稳定的 regime 标签与置信度
    - 为 AI 决策层与研究报告提供统一接口

    当前实现（v1）：
    - 仅基于 ETF 日线缓存计算：短中期动量 + 20 日波动 + 60 日回撤
    - 输出 regime ∈ {trending_up, trending_down, range, high_vol_risk}
    """
    from datetime import datetime

    import numpy as np
    import pandas as pd

    from merged.read_market_data import tool_read_market_data

    out = tool_read_market_data(data_type="etf_daily", symbol=symbol)
    if not out.get("success"):
        return {"success": False, "message": f"read etf_daily failed: {out.get('message')}", "data": None}

    raw = out.get("data")
    if isinstance(raw, list):
        df = pd.DataFrame(raw)
    elif isinstance(raw, dict):
        nested = raw.get("records") or raw.get("rows") or raw.get("data")
        if isinstance(nested, list):
            df = pd.DataFrame(nested)
        elif isinstance(nested, dict):
            try:
                df = pd.DataFrame(nested)
            except Exception:
                return {"success": False, "message": "etf_daily nested dict is not columnar", "data": None}
        else:
            try:
                df = pd.DataFrame(raw)
            except Exception:
                return {"success": False, "message": "etf_daily cache shape not tabular", "data": None}
    else:
        return {"success": False, "message": "empty etf_daily cache payload", "data": None}
    cols = {c.lower(): c for c in df.columns}
    close_col = cols.get("close") or cols.get("收盘") or cols.get("收盘价")
    if not close_col:
        return {"success": False, "message": "close column not found in cache data", "data": None}

    s = pd.to_numeric(df[close_col], errors="coerce").dropna()
    if len(s) < 70:
        return {"success": False, "message": "insufficient daily data for regime detection", "data": None}

    m20 = float((s.iloc[-1] / s.iloc[-21]) - 1.0)
    m60 = float((s.iloc[-1] / s.iloc[-61]) - 1.0)
    rets = s.pct_change().dropna()
    vol20 = float(rets.iloc[-20:].std(ddof=0) * np.sqrt(252))

    window = s.iloc[-60:]
    roll_max = window.cummax()
    dd = (window / roll_max) - 1.0
    mdd60 = float(dd.min())

    # Heuristic thresholds (tunable)
    high_vol = vol20 >= 0.30
    strong_up = (m20 >= 0.02) and (m60 >= 0.04)
    strong_down = (m20 <= -0.02) and (m60 <= -0.04)
    deep_dd = mdd60 <= -0.08

    if high_vol and deep_dd:
        regime = "high_vol_risk"
        confidence = 0.75
    elif strong_up and not high_vol:
        regime = "trending_up"
        confidence = 0.70
    elif strong_down and not high_vol:
        regime = "trending_down"
        confidence = 0.70
    else:
        regime = "range"
        confidence = 0.55

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "success": True,
        "message": "market_regime ok",
        "data": {
            "timestamp": ts,
            "symbol": symbol,
            "regime": regime,
            "confidence": confidence,
            "features": {
                "momentum_20d": m20,
                "momentum_60d": m60,
                "vol_20d": vol20,
                "max_drawdown_60d": mdd60,
            },
        },
    }

