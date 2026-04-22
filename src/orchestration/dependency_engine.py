from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ConditionFn = Callable[[dict[str, Any]], tuple[bool, str]]


@dataclass(frozen=True)
class DependencyEvaluation:
    passed: bool
    failed_conditions: list[str]
    details: dict[str, str]


class DependencyEngine:
    def __init__(self) -> None:
        self._rules: dict[str, ConditionFn] = {
            "emergency_pause_active": self._emergency_pause_active,
            "sentiment_stage_not_extreme": self._sentiment_stage_not_extreme,
            "sentiment_dispersion_low": self._sentiment_dispersion_low,
            "position_ceiling_positive": self._position_ceiling_positive,
            "is_trading_day": self._is_trading_day,
        }

    def evaluate(self, context: dict[str, Any], conditions: list[str]) -> DependencyEvaluation:
        failed: list[str] = []
        details: dict[str, str] = {}
        for cond in conditions:
            rule = self._rules.get(cond)
            if rule is None:
                failed.append(cond)
                details[cond] = "condition_not_registered"
                continue
            ok, reason = rule(context)
            details[cond] = reason
            if not ok:
                failed.append(cond)
        return DependencyEvaluation(passed=not failed, failed_conditions=failed, details=details)

    def _emergency_pause_active(self, context: dict[str, Any]) -> tuple[bool, str]:
        active = bool(context.get("emergency_pause_active"))
        return (not active, "ok" if not active else "condition_not_met:emergency_pause_active")

    def _sentiment_stage_not_extreme(self, context: dict[str, Any]) -> tuple[bool, str]:
        stage = str(context.get("sentiment_stage") or "")
        extreme_markers = ("冰点", "退潮", "极端", "panic", "extreme")
        is_extreme = any(x in stage.lower() for x in [m.lower() for m in extreme_markers]) or any(
            x in stage for x in extreme_markers
        )
        return (not is_extreme, "ok" if not is_extreme else f"condition_not_met:sentiment_stage={stage}")

    def _sentiment_dispersion_low(self, context: dict[str, Any]) -> tuple[bool, str]:
        value = context.get("sentiment_dispersion")
        threshold = float(context.get("sentiment_dispersion_threshold") or 0.6)
        if not isinstance(value, (int, float)):
            return False, "condition_not_met:sentiment_dispersion_missing"
        ok = float(value) <= threshold
        return (ok, "ok" if ok else f"condition_not_met:sentiment_dispersion={value}>{threshold}")

    def _position_ceiling_positive(self, context: dict[str, Any]) -> tuple[bool, str]:
        value = context.get("position_ceiling")
        if not isinstance(value, (int, float)):
            return False, "condition_not_met:position_ceiling_missing"
        ok = float(value) > 0
        return (ok, "ok" if ok else f"condition_not_met:position_ceiling={value}")

    def _is_trading_day(self, context: dict[str, Any]) -> tuple[bool, str]:
        return (bool(context.get("is_trading_day")), "ok" if context.get("is_trading_day") else "condition_not_met:not_trading_day")
