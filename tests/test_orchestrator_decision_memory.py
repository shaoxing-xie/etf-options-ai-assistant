"""决策记忆 JSONL 与反思规则。"""

from __future__ import annotations

import json
from pathlib import Path

from src.orchestrator.decision_memory import (
    append_decision_reflection,
    build_memory_injection_text,
    memory_jsonl_path,
    rule_reflection_from_range_hit,
)


def test_rule_reflection_range():
    r = rule_reflection_from_range_hit(symbol="510300", hit=True, coverage_rate=0.9)
    assert r["was_correct"] is True
    assert "命中" in r["key_lesson"]


def test_append_and_read_injection(tmp_path: Path):
    append_decision_reflection(
        task_id="prediction-verification-reflection",
        run_id="r1",
        trade_date="2026-05-05",
        entity="510300",
        reflection=rule_reflection_from_range_hit(symbol="510300", hit=False, coverage_rate=0.1),
        root=tmp_path,
    )
    path = memory_jsonl_path(tmp_path, "2026-05-05")
    assert path.is_file()
    line = path.read_text(encoding="utf-8").strip().splitlines()[0]
    row = json.loads(line)
    assert row["_meta"]["schema_name"] == "decision_reflection_v1"
    text = build_memory_injection_text(entity="510300", trade_date="2026-05-05", root=tmp_path)
    assert "510300" in text
