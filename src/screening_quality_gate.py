"""tool_screen_equity_factors 结果与 `tool_payload_quality` / 策略配置的门禁。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.tool_payload_quality import effective_quality_score


def _policy() -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    p = root / "config" / "data_quality_policy.yaml"
    if not p.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def screening_allow_watchlist(payload: Optional[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    是否允许写入观察池：质量分阈值 + degraded + screening 策略。
    """
    reasons: List[str] = []
    if not isinstance(payload, dict):
        return False, ["not_a_dict"]
    if not payload.get("success"):
        return False, ["screening_success_false"]
    pol = (_policy().get("screening") or {}) if isinstance(_policy(), dict) else {}
    min_q = float(pol.get("min_quality_score", 55))
    block_if_degraded = bool(pol.get("block_watchlist_if_degraded", False))

    qs, _miss = effective_quality_score(payload)
    if qs < min_q:
        reasons.append(f"quality_score {qs} < {min_q}")
    if block_if_degraded and payload.get("degraded"):
        reasons.append("degraded_true")

    return len(reasons) == 0, reasons


def screening_should_skip_due_to_pause() -> Tuple[bool, str]:
    """紧急暂停或周度 regime=pause 时跳过观察池写入（仍可落盘 screening 审计）。"""
    from src.screening_gate_files import is_emergency_pause_active, read_weekly_regime_pause

    if read_weekly_regime_pause():
        return True, "weekly_calibration.regime=pause"
    if is_emergency_pause_active():
        return True, "emergency_pause.json active"
    return False, ""
