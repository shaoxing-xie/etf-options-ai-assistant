"""
A股可交易性过滤（最小可用版）。

当前实现基于实时行情快照做启发式判断：
- 疑似停牌：价格无效或成交量为 0
- 疑似涨跌停：涨跌幅接近 10%（主板/创业板/科创板不同阈值后续可细化）

注意：更权威的停复牌/风险警示/退市整理信息需要专门数据源接入；
这里先提供可扩展的输出结构，保证上层 Guard 能稳定消费。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from plugins.data_collection.stock.fetch_realtime import tool_fetch_stock_realtime


@dataclass(frozen=True)
class TradabilityThresholds:
    limit_up_down_pct_main: float = 9.8  # 主板常见 10%（留 buffer）
    limit_up_down_pct_alt: float = 19.5  # 创业板/科创板常见 20%（留 buffer）


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _is_alt_board(code: str) -> bool:
    # 简化：3xxxx 创业板；688xxx 科创板（更完整应包含 30/68/8 等规则）
    c = (code or "").strip()
    return c.startswith("3") or c.startswith("688")


def filter_a_share_tradability(
    stock_codes: List[str],
    *,
    assume_tradable_if_unknown: bool = False,
) -> Dict[str, Any]:
    thresholds = TradabilityThresholds()
    codes = [str(x).strip() for x in (stock_codes or []) if str(x).strip()]
    if not codes:
        return {"success": False, "message": "未提供股票代码", "data": None}

    rt = tool_fetch_stock_realtime(stock_code=",".join(codes), mode="test")
    rows: List[Dict[str, Any]] = []
    if rt.get("success") and rt.get("data"):
        d = rt.get("data")
        if isinstance(d, list):
            rows = [x for x in d if isinstance(x, dict)]
        elif isinstance(d, dict):
            rows = [d]

    by_code: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        cc = str(r.get("stock_code") or r.get("code") or "").strip()
        if cc:
            by_code[cc] = r

    results: List[Dict[str, Any]] = []
    for code in codes:
        r = by_code.get(code)
        if not r:
            results.append(
                {
                    "stock_code": code,
                    "tradable": assume_tradable_if_unknown,
                    "status": "unknown",
                    "reasons": ["realtime_quote_unavailable"],
                    "raw": None,
                }
            )
            continue

        price = _safe_float(r.get("current_price") or r.get("price"), 0.0)
        volume = _safe_float(r.get("volume") or r.get("vol"), 0.0)
        pct = _safe_float(r.get("change_percent") or r.get("pct_chg"), 0.0)

        reasons: List[str] = []
        status = "normal"
        tradable = True

        # Suspended heuristic
        if price <= 0 or volume <= 0:
            tradable = False
            status = "suspended_suspected"
            reasons.append("no_trade_or_invalid_price")

        # Limit up/down heuristic
        limit_th = thresholds.limit_up_down_pct_alt if _is_alt_board(code) else thresholds.limit_up_down_pct_main
        if abs(pct) >= limit_th:
            status = "limit_up_down_suspected"
            reasons.append(f"pct_change_near_limit({pct:.2f}%)")

        results.append(
            {
                "stock_code": code,
                "name": r.get("name"),
                "tradable": tradable,
                "status": status,
                "reasons": reasons,
                "quote": {
                    "current_price": price,
                    "change_percent": pct,
                    "volume": volume,
                    "prev_close": _safe_float(r.get("prev_close"), 0.0),
                },
                "source": rt.get("source"),
            }
        )

    return {"success": True, "message": "tradability filter ok", "data": {"results": results, "count": len(results)}}


def tool_filter_a_share_tradability(
    stock_codes: str,
    assume_tradable_if_unknown: bool = False,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：A股可交易性过滤

    Args:
        stock_codes: 逗号分隔代码列表
        assume_tradable_if_unknown: 无法获取行情时是否默认可交易（默认 False）
    """
    codes = [x.strip() for x in (stock_codes or "").split(",") if x.strip()]
    return filter_a_share_tradability(codes, assume_tradable_if_unknown=assume_tradable_if_unknown)

