"""Registry 加载与拓扑工具测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.orchestrator.registry import (
    collect_task_dependency_closure,
    load_tasks_registry,
    task_execution_plan,
    topological_order,
)


def test_load_tasks_registry():
    reg = load_tasks_registry()
    assert reg.orchestrator_enabled is True
    assert "daily_health" in reg.tasks
    dh = reg.tasks["daily_health"]
    assert dh.enabled is True
    assert len(dh.steps) >= 1


def test_topological_order_linear():
    edges = {"b": ["a"], "c": ["b"]}
    order = topological_order(["c", "a", "b"], edges)
    assert order.index("a") < order.index("b") < order.index("c")


def test_registry_path_explicit(tmp_path: Path):
    p = tmp_path / "tasks_registry.yaml"
    p.write_text(
        """
version: "1"
orchestrator:
  enabled: true
defaults: {}
tasks:
  - id: x
    enabled: true
    deprecated: true
    replacement_task_id: y
    steps: []
""",
        encoding="utf-8",
    )
    reg = load_tasks_registry(p)
    assert "x" in reg.tasks
    assert reg.tasks["x"].deprecated is True
    assert reg.tasks["x"].replacement_task_id == "y"


def test_task_execution_plan_linear(tmp_path: Path):
    p = tmp_path / "r.yaml"
    p.write_text(
        """
version: "1"
orchestrator: { enabled: true }
defaults: {}
tasks:
  - id: base
    enabled: true
    dependencies: []
    steps:
      - id: s0
        kind: tool
        tool: tool_plugin_catalog_digest
        params: {}
  - id: top
    enabled: true
    dependencies: [base]
    steps:
      - id: s1
        kind: tool
        tool: tool_plugin_catalog_digest
        params: {}
""",
        encoding="utf-8",
    )
    reg = load_tasks_registry(p)
    plan, err = task_execution_plan(reg, "top")
    assert err is None and plan == ["base", "top"]


def test_task_execution_plan_cycle(tmp_path: Path):
    p = tmp_path / "r.yaml"
    p.write_text(
        """
version: "1"
orchestrator: { enabled: true }
defaults: {}
tasks:
  - id: a
    enabled: true
    dependencies: [b]
    steps: []
  - id: b
    enabled: true
    dependencies: [a]
    steps: []
""",
        encoding="utf-8",
    )
    reg = load_tasks_registry(p)
    _nodes, err = collect_task_dependency_closure(reg, "a")
    assert err == "dependency_cycle"
    plan, err2 = task_execution_plan(reg, "a")
    assert plan is None and err2 == "dependency_cycle"


def test_task_execution_plan_unknown_dep(tmp_path: Path):
    p = tmp_path / "r.yaml"
    p.write_text(
        """
version: "1"
orchestrator: { enabled: true }
defaults: {}
tasks:
  - id: x
    enabled: true
    dependencies: [missing]
    steps: []
""",
        encoding="utf-8",
    )
    reg = load_tasks_registry(p)
    plan, err = task_execution_plan(reg, "x")
    assert plan is None and err == "unknown_dependency:missing"
