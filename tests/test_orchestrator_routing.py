"""条件路由与安全比较求值。"""

from __future__ import annotations

from pathlib import Path

from src.orchestrator.registry import StepDef, TaskDef, load_tasks_registry
from src.orchestrator.routing import (
    resolve_next_step_id,
    routing_condition_matches,
    validate_step_graph,
)


def test_routing_condition_quality_status():
    doc = {"ok": True, "output": {"quality_status": "error"}, "step_id": "a"}
    assert routing_condition_matches("output.quality_status == error", doc)
    assert not routing_condition_matches("output.quality_status == ok", doc)


def test_routing_condition_ok():
    doc = {"ok": False, "output": {}, "step_id": "a"}
    assert routing_condition_matches("ok == false", doc)
    assert not routing_condition_matches("ok == true", doc)


def test_resolve_next_routing_over_sequential():
    task = TaskDef(
        id="t",
        steps=[
            StepDef(id="a", kind="tool", tool="x"),
            StepDef(id="b", kind="tool", tool="x"),
        ],
        branch_steps=[StepDef(id="fallback", kind="tool", tool="y")],
        routing=(
            {
                "source_step": "a",
                "conditions": [{"when": "output.quality_status == error", "target": "fallback"}],
                "default": "b",
            },
        ),
    )
    nxt = resolve_next_step_id(
        task, current_step_id="a", step_ok=True, output={"quality_status": "error"}
    )
    assert nxt == "fallback"
    nxt2 = resolve_next_step_id(
        task, current_step_id="a", step_ok=True, output={"quality_status": "ok"}
    )
    assert nxt2 == "b"


def test_validate_step_graph_duplicate_branch():
    task = TaskDef(
        id="t",
        steps=[StepDef(id="a", kind="tool", tool="x")],
        branch_steps=[StepDef(id="a", kind="tool", tool="y")],
    )
    assert validate_step_graph(task) == "branch_step_duplicates_main:a"


def test_registry_loads_routing_yaml(tmp_path: Path):
    p = tmp_path / "r.yaml"
    p.write_text(
        """
version: "1"
orchestrator: { enabled: true }
defaults: {}
tasks:
  - id: rt
    enabled: true
    steps:
      - id: s1
        kind: tool
        tool: tool_plugin_catalog_digest
        params: {}
      - id: s2
        kind: tool
        tool: tool_plugin_catalog_digest
        params: {}
    branch_steps:
      - id: fb
        kind: tool
        tool: tool_plugin_catalog_digest
        params: {}
    routing:
      - source_step: s1
        conditions:
          - when: "output.success == false"
            target: fb
        default: s2
""",
        encoding="utf-8",
    )
    reg = load_tasks_registry(p)
    t = reg.tasks["rt"]
    assert len(t.branch_steps) == 1
    assert len(t.routing) == 1
