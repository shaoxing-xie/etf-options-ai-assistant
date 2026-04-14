from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


VALID_GROUPS = {"technical", "volatility", "regime"}
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_OPERATORS = {">", ">=", "<", "<=", "==", "!="}


@dataclass
class AlertCondition:
    type: str
    metric: str
    operator: str
    value: float


@dataclass
class AlertRule:
    rule_id: str
    contract_version: str
    enabled: bool
    symbol: str
    timeframe: str
    group: str
    priority: str
    condition: AlertCondition
    cooldown_sec: int = 300
    ttl_sec: int = 86400
    notify: Dict[str, Any] = field(default_factory=dict)
    actions: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


def validate_rule_obj(raw: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required = ["rule_id", "contract_version", "symbol", "timeframe", "group", "priority", "condition"]
    for key in required:
        if key not in raw:
            errors.append(f"missing field: {key}")

    group = str(raw.get("group", "")).strip().lower()
    if group and group not in VALID_GROUPS:
        errors.append(f"invalid group: {group}")
    prio = str(raw.get("priority", "")).strip().lower()
    if prio and prio not in VALID_PRIORITIES:
        errors.append(f"invalid priority: {prio}")

    cond = raw.get("condition") if isinstance(raw.get("condition"), dict) else {}
    op = str(cond.get("operator", "")).strip()
    if op and op not in VALID_OPERATORS:
        errors.append(f"invalid operator: {op}")
    if cond and "metric" not in cond:
        errors.append("condition.metric is required")
    if cond and "value" not in cond:
        errors.append("condition.value is required")
    return errors


def parse_rule(raw: Dict[str, Any]) -> AlertRule:
    cond_raw = raw.get("condition") or {}
    cond = AlertCondition(
        type=str(cond_raw.get("type", "threshold")),
        metric=str(cond_raw.get("metric", "")),
        operator=str(cond_raw.get("operator", ">=")),
        value=float(cond_raw.get("value", 0)),
    )
    return AlertRule(
        rule_id=str(raw["rule_id"]),
        contract_version=str(raw.get("contract_version", "1.0")),
        enabled=bool(raw.get("enabled", True)),
        symbol=str(raw["symbol"]),
        timeframe=str(raw["timeframe"]),
        group=str(raw["group"]).lower(),
        priority=str(raw["priority"]).lower(),
        condition=cond,
        cooldown_sec=int(raw.get("cooldown_sec", 300)),
        ttl_sec=int(raw.get("ttl_sec", 86400)),
        notify=raw.get("notify") if isinstance(raw.get("notify"), dict) else {},
        actions=raw.get("actions") if isinstance(raw.get("actions"), dict) else {},
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )

