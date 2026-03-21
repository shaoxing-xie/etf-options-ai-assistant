"""
合并工具：仓位与硬限制
action: calculate | check | apply
"""

from typing import Dict, Any, Optional

def tool_position_limit(
    action: str,
    trend_strength: Optional[float] = None,
    signal_confidence: Optional[float] = None,
    account_value: Optional[float] = 100000,
    etf_current_price: Optional[float] = 4.0,
    apply_hard_limit: Optional[bool] = False,
    hard_limit_pct: Optional[float] = None,
    current_position_value: Optional[float] = None,
    recommended_size: Optional[float] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    仓位计算/检查/硬锁定（统一入口）。
    action: calculate | check | apply
    """
    if action == "calculate":
        from analysis.etf_position_manager import tool_calculate_position_size
        return tool_calculate_position_size(
            trend_strength=trend_strength or 0.7,
            signal_confidence=signal_confidence or 0.8,
            account_value=account_value or 100000,
            etf_current_price=etf_current_price or 4.0,
            apply_hard_limit=apply_hard_limit if apply_hard_limit is not None else False,
            hard_limit_pct=hard_limit_pct,
            **kwargs
        )
    if action == "check":
        from analysis.etf_position_manager import tool_check_position_limit
        if current_position_value is None or account_value is None:
            return {"success": False, "message": "check 需要 current_position_value 和 account_value", "data": None}
        return tool_check_position_limit(
            current_position_value=current_position_value,
            account_value=account_value,
            hard_limit_pct=hard_limit_pct,
            **kwargs
        )
    if action == "apply":
        from analysis.etf_position_manager import tool_apply_hard_limit
        if recommended_size is None or account_value is None or etf_current_price is None:
            return {"success": False, "message": "apply 需要 recommended_size, account_value, etf_current_price", "data": None}
        return tool_apply_hard_limit(
            recommended_size=recommended_size,
            account_value=account_value,
            etf_current_price=etf_current_price,
            hard_limit_pct=hard_limit_pct,
            **kwargs
        )
    return {
        "success": False,
        "message": f"不支持的 action: {action}，应为 calculate | check | apply",
        "data": None
    }
