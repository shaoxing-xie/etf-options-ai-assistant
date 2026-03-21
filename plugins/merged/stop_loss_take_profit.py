"""
合并工具：止盈止损
action: calculate | check
"""

from typing import Dict, Any, Optional

def tool_stop_loss_take_profit(
    action: str,
    entry_price: Optional[float] = None,
    current_price: Optional[float] = None,
    trend_direction: Optional[str] = None,
    etf_symbol: Optional[str] = "510300",
    highest_price: Optional[float] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    止盈止损计算或检查（统一入口）。
    action: calculate | check
    """
    if action == "calculate":
        from analysis.etf_risk_manager import tool_calculate_stop_loss_take_profit
        if entry_price is None or current_price is None or trend_direction is None:
            return {"success": False, "message": "calculate 需要 entry_price, current_price, trend_direction", "data": None}
        return tool_calculate_stop_loss_take_profit(
            entry_price=entry_price,
            current_price=current_price,
            trend_direction=trend_direction,
            **kwargs
        )
    if action == "check":
        from analysis.etf_risk_manager import tool_check_stop_loss_take_profit
        if None in (entry_price, current_price, highest_price):
            return {"success": False, "message": "check 需要 etf_symbol, entry_price, current_price, highest_price", "data": None}
        return tool_check_stop_loss_take_profit(
            etf_symbol=etf_symbol or "510300",
            entry_price=entry_price,
            current_price=current_price,
            highest_price=highest_price,
            **kwargs
        )
    return {
        "success": False,
        "message": f"不支持的 action: {action}，应为 calculate | check",
        "data": None
    }
