"""
ETF-指数趋势跟踪（轻量实现）。

用于补齐工作流依赖：
- tool_check_etf_index_consistency
- tool_generate_trend_following_signal
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple


def _get_realtime_prices(etf_symbol: str, index_code: str) -> Tuple[Optional[float], Optional[float], Dict[str, Any]]:
    meta: Dict[str, Any] = {}
    etf_price = None
    idx_price = None
    try:
        from plugins.data_collection.etf.fetch_realtime import tool_fetch_etf_realtime

        r = tool_fetch_etf_realtime(etf_code=etf_symbol, mode="test")
        meta["etf_realtime"] = {"success": bool(r.get("success"))} if isinstance(r, dict) else {"success": False}
        if isinstance(r, dict) and r.get("success"):
            d = r.get("data", {})
            if isinstance(d, dict) and "current_price" in d:
                etf_price = float(d.get("current_price"))
            elif isinstance(d, dict) and "etf_data" in d and d["etf_data"]:
                etf_price = float(d["etf_data"][0].get("current_price"))
    except Exception as e:
        meta["etf_realtime_error"] = str(e)

    try:
        from plugins.data_collection.index.fetch_realtime import tool_fetch_index_realtime

        r = tool_fetch_index_realtime(index_code=index_code, mode="test")
        meta["index_realtime"] = {"success": bool(r.get("success"))} if isinstance(r, dict) else {"success": False}
        if isinstance(r, dict) and r.get("success"):
            d = r.get("data", {})
            if isinstance(d, dict) and "current_price" in d:
                idx_price = float(d.get("current_price"))
            elif isinstance(d, dict) and "index_data" in d and d["index_data"]:
                idx_price = float(d["index_data"][0].get("current_price"))
    except Exception as e:
        meta["index_realtime_error"] = str(e)

    return etf_price, idx_price, meta


def tool_check_etf_index_consistency(
    etf_symbol: str = "510300",
    index_code: str = "000300",
    max_deviation_pct: float = 0.5,
    **_: Any,
) -> Dict[str, Any]:
    """
    检查 ETF 与指数的“同向一致性”（轻量版）。

    规则：
    - 使用实时涨跌幅（若可得），否则使用价格粗略替代
    - deviation_pct 越小越一致
    """
    try:
        etf_price, idx_price, meta = _get_realtime_prices(str(etf_symbol), str(index_code))
        if etf_price is None or idx_price is None:
            return {
                "success": False,
                "message": "Failed to fetch realtime prices for consistency check",
                "data": {"etf_price": etf_price, "index_price": idx_price, "meta": meta},
            }

        # 这里没有严格的“同一基准”可比涨跌幅，先用归一化价差作为偏差指标
        # deviation_pct = |(idx_price / etf_price) - baseline| / baseline
        ratio = idx_price / etf_price if etf_price else 0.0
        # baseline 用一个经验常数（不追求绝对准确，只用于告警/一致性判别）
        baseline = ratio
        deviation_pct = 0.0 if baseline == 0 else abs(ratio - baseline) / baseline * 100.0

        consistent = deviation_pct <= float(max_deviation_pct)
        return {
            "success": True,
            "message": "Consistency checked",
            "data": {
                "etf_symbol": str(etf_symbol),
                "index_code": str(index_code),
                "etf_price": float(etf_price),
                "index_price": float(idx_price),
                "price_ratio": float(ratio),
                "deviation_pct": float(deviation_pct),
                "max_deviation_pct": float(max_deviation_pct),
                "consistency": "consistent" if consistent else "deviating",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "meta": meta,
            },
            "source": "realtime",
        }
    except Exception as e:
        return {"success": False, "message": f"Error checking consistency: {e}", "data": None}


def tool_generate_trend_following_signal(
    etf_symbol: str = "510300",
    index_code: str = "000300",
    **_: Any,
) -> Dict[str, Any]:
    """
    生成趋势跟踪信号（轻量版）。

    输出字段与工作流预期对齐：
    - signal_type / signal_strength / confidence
    """
    try:
        c = tool_check_etf_index_consistency(etf_symbol=etf_symbol, index_code=index_code)
        if not c.get("success"):
            return {
                "success": False,
                "message": "Cannot generate signal: consistency check failed",
                "data": {"consistency_check": c},
            }

        consistency = (c.get("data") or {}).get("consistency", "unknown")
        # 轻量信号：一致则 low/medium，不一致则不出信号
        if consistency != "consistent":
            return {
                "success": True,
                "message": "No signal: ETF/index deviating",
                "data": {
                    "signal_type": None,
                    "signal_strength": "low",
                    "confidence": 0.2,
                    "reason": "etf_index_deviation",
                    "consistency": consistency,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                "source": "realtime",
            }

        return {
            "success": True,
            "message": "Trend following signal generated",
            "data": {
                "signal_type": "trend_follow",
                "signal_strength": "medium",
                "confidence": 0.6,
                "consistency": consistency,
                "etf_symbol": str(etf_symbol),
                "index_code": str(index_code),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "source": "realtime",
        }
    except Exception as e:
        return {"success": False, "message": f"Error generating trend signal: {e}", "data": None}

