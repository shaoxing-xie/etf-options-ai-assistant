from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class IndicatorRuntimeDecision:
    route: str
    migration_enabled: bool
    dual_run: bool
    rollback_enabled: bool
    notes: List[str]


def _load_migration_cfg() -> Dict[str, Any]:
    try:
        from src.config_loader import load_system_config

        cfg = load_system_config(use_cache=True)
        block = (cfg or {}).get("indicator_migration")
        return block if isinstance(block, dict) else {}
    except Exception:
        return {}


def resolve_indicator_runtime(task_key: str) -> IndicatorRuntimeDecision:
    """
    统一解析技术指标迁移开关。

    route:
      - plugin_tool: 统一走 tool_calculate_technical_indicators
      - direct_engine: 允许任务内部直接引擎调用（高风险链路）
    """
    cfg = _load_migration_cfg()
    tasks = cfg.get("tasks") if isinstance(cfg.get("tasks"), dict) else {}
    tcfg = tasks.get(task_key) if isinstance(tasks.get(task_key), dict) else {}

    route = str(tcfg.get("route") or cfg.get("default_route") or "plugin_tool").strip().lower()
    if route not in ("plugin_tool", "direct_engine"):
        route = "plugin_tool"

    migration_enabled = bool(tcfg.get("enabled", cfg.get("enabled", True)))
    dual_run = bool(tcfg.get("dual_run", cfg.get("dual_run_default", False)))
    rollback_enabled = bool(tcfg.get("rollback_enabled", cfg.get("rollback_enabled", True)))

    notes: List[str] = []
    if not migration_enabled:
        notes.append("migration_disabled")
    if dual_run:
        notes.append("dual_run_enabled")
    if rollback_enabled:
        notes.append("rollback_enabled")

    return IndicatorRuntimeDecision(
        route=route,
        migration_enabled=migration_enabled,
        dual_run=dual_run,
        rollback_enabled=rollback_enabled,
        notes=notes,
    )


def calculate_indicators_via_tool(
    *,
    symbol: str,
    data_type: str,
    indicators: Optional[List[str]] = None,
    lookback_days: int = 120,
    timeframe_minutes: Optional[int] = None,
    ma_periods: Optional[List[int]] = None,
    rsi_length: Optional[int] = None,
) -> Dict[str, Any]:
    """
    统一入口：通过插件工具计算指标，返回原工具结果。
    """
    from plugins.analysis.technical_indicators import tool_calculate_technical_indicators

    return tool_calculate_technical_indicators(
        symbol=symbol,
        data_type=data_type,
        indicators=indicators,
        lookback_days=lookback_days,
        timeframe_minutes=timeframe_minutes,
        ma_periods=ma_periods,
        rsi_length=rsi_length,
    )

