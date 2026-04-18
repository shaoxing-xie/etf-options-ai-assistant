"""
Unified indicator facade tool.

This tool is the migration entrypoint for workflows/agents and delegates
indicator calculations to the runtime facade.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.services.indicator_runtime import calculate_indicators_via_tool, resolve_indicator_runtime


def tool_calculate_technical_indicators_unified(
    symbol: str = "510300",
    data_type: str = "etf_daily",
    period: Optional[str] = None,
    lookback_days: int = 120,
    engine: Optional[str] = None,
    indicators: Optional[List[str]] = None,
    timeframe_minutes: Optional[int] = None,
    ma_periods: Optional[List[int]] = None,
    rsi_length: Optional[int] = None,
    task_key: str = "workflow_default",
) -> Dict[str, Any]:
    """
    Unified external tool for technical indicators.

    Notes:
    - Keeps compatibility with old workflow parameters.
    - `engine`/`period` are accepted for compatibility but ignored here.
    """
    _ = period
    _ = engine
    runtime = resolve_indicator_runtime(task_key)
    out = calculate_indicators_via_tool(
        symbol=symbol,
        data_type=data_type,
        indicators=indicators,
        lookback_days=lookback_days,
        timeframe_minutes=timeframe_minutes,
        ma_periods=ma_periods,
        rsi_length=rsi_length,
    )
    if isinstance(out, dict):
        out.setdefault("meta", {})
        if isinstance(out["meta"], dict):
            out["meta"]["indicator_runtime"] = {
                "task_key": task_key,
                "route": runtime.route,
                "migration_enabled": runtime.migration_enabled,
                "dual_run": runtime.dual_run,
                "rollback_enabled": runtime.rollback_enabled,
                "notes": runtime.notes,
            }
    return out

