"""跨任务依赖：执行顺序与 step_id 前缀。"""

from __future__ import annotations

from pathlib import Path

from src.orchestrator.dag_executor import DAGExecutor
from src.orchestrator.registry import load_tasks_registry


def test_execute_runs_dependencies_first_dry_run(tmp_path: Path):
    p = tmp_path / "r.yaml"
    p.write_text(
        """
version: "1"
orchestrator: { enabled: true }
defaults: {}
tasks:
  - id: parent
    enabled: true
    dependencies: []
    steps:
      - id: pstep
        kind: tool
        tool: tool_plugin_catalog_digest
        params: {}
  - id: child
    enabled: true
    dependencies: [parent]
    steps:
      - id: cstep
        kind: tool
        tool: tool_plugin_catalog_digest
        params: {}
""",
        encoding="utf-8",
    )
    reg = load_tasks_registry(p)
    ex = DAGExecutor(registry=reg)
    res = ex.execute("child", dry_run=True, trade_date="2026-04-30")
    assert res.success is True
    assert res.dependency_execution_order == ["parent", "child"]
    assert [s.step_id for s in res.steps] == ["parent::pstep", "child::cstep"]
