from __future__ import annotations

from typing import Any


def resolve_l4_confidence(l4_result: dict[str, Any]) -> float | None:
    """从工具返回或语义快照结构中解析 confidence（契约字段优先）。"""
    meta = l4_result.get("_meta")
    if isinstance(meta, dict):
        c = meta.get("confidence")
        if isinstance(c, (int, float)):
            return float(c)
    data = l4_result.get("data")
    if isinstance(data, dict):
        c = data.get("confidence")
        if isinstance(c, (int, float)):
            return float(c)
    return None


def apply_l4_gate(l4_result: dict[str, Any], gate_config: dict[str, Any]) -> str:
    """
    返回: pass | degrade | block | alert_only
    """
    conf = resolve_l4_confidence(l4_result)
    if conf is None:
        conf = 0.0
    min_confidence = float(gate_config.get("min_confidence", 0.6))
    on_fail = str(gate_config.get("on_fail", "alert_only")).strip().lower()

    if conf >= min_confidence:
        return "pass"
    if on_fail == "block":
        return "block"
    if on_fail == "degrade":
        return "degrade"
    return "alert_only"
