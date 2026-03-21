"""
合并工具：策略权重 get / adjust
action: get | adjust
"""

from typing import Dict, Any, Optional, List

def tool_strategy_weights(
    action: str,
    strategies: Optional[List[str]] = None,
    current_weights: Optional[Dict[str, float]] = None,
    lookback_days: Optional[int] = 60,
    adjustment_rate: Optional[float] = 0.1,
    **kwargs
) -> Dict[str, Any]:
    """
    策略权重查询或调整（统一入口）。
    action: get | adjust
    """
    if action == "get":
        from analysis.strategy_weight_manager import tool_get_strategy_weights
        return tool_get_strategy_weights(strategies=strategies, **kwargs)
    if action == "adjust":
        from analysis.strategy_weight_manager import tool_adjust_strategy_weights
        if not current_weights:
            return {"success": False, "message": "adjust 需要 current_weights", "data": None}
        return tool_adjust_strategy_weights(
            current_weights=current_weights,
            lookback_days=lookback_days or 60,
            adjustment_rate=adjustment_rate or 0.1,
            **kwargs
        )
    return {
        "success": False,
        "message": f"不支持的 action: {action}，应为 get | adjust",
        "data": None
    }
