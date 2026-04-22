from __future__ import annotations

from src.orchestration.dependency_engine import DependencyEngine


def test_dependency_engine_passes_registered_rules() -> None:
    eng = DependencyEngine()
    result = eng.evaluate(
        {
            "is_trading_day": True,
            "emergency_pause_active": False,
            "sentiment_stage": "中性",
            "sentiment_dispersion": 0.3,
            "position_ceiling": 0.6,
        },
        ["is_trading_day", "emergency_pause_active", "sentiment_stage_not_extreme", "sentiment_dispersion_low", "position_ceiling_positive"],
    )
    assert result.passed is True
    assert result.failed_conditions == []


def test_dependency_engine_rejects_unknown_rule() -> None:
    eng = DependencyEngine()
    result = eng.evaluate({"is_trading_day": True}, ["unknown_condition"])
    assert result.passed is False
    assert "unknown_condition" in result.failed_conditions
    assert result.details["unknown_condition"] == "condition_not_registered"
