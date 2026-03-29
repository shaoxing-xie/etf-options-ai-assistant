"""
合并工具：策略表现/评分查询
action: performance | score
"""

from typing import Dict, Any, Optional

def tool_strategy_analytics(
    action: str,
    strategy: Optional[str] = None,
    lookback_days: Optional[int] = 60,
    min_signals: Optional[int] = 10,
    **kwargs
) -> Dict[str, Any]:
    """
    策略表现或评分（统一入口）。
    action: performance | score
    """
    if action == "performance":
        from analysis.strategy_tracker import tool_get_strategy_performance
        if not strategy:
            return {"success": False, "message": "performance 需要 strategy", "data": None}
        perf_kwargs = {k: v for k, v in kwargs.items() if k in (
            "start_date", "end_date", "trading_costs", "by_regime",
        )}
        return tool_get_strategy_performance(
            strategy=strategy,
            lookback_days=lookback_days or 60,
            **perf_kwargs,
        )
    if action == "score":
        from analysis.strategy_evaluator import tool_calculate_strategy_score
        if not strategy:
            return {"success": False, "message": "score 需要 strategy", "data": None}
        score_kwargs = {k: v for k, v in kwargs.items() if k in (
            "start_date", "end_date", "trading_costs", "param_count",
            "complexity_penalty_per_param", "complexity_penalty_cap",
        )}
        return tool_calculate_strategy_score(
            strategy=strategy,
            lookback_days=lookback_days or 60,
            min_signals=min_signals or 10,
            **score_kwargs,
        )
    return {
        "success": False,
        "message": f"不支持的 action: {action}，应为 performance | score",
        "data": None
    }
