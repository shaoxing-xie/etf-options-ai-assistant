"""DAG 执行器 dry-run（不触网、不子进程）。"""

from __future__ import annotations

from pathlib import Path

from src.orchestrator.dag_executor import DAGExecutor
from src.orchestrator.registry import load_tasks_registry


def test_daily_health_dry_run():
    reg = load_tasks_registry()
    ex = DAGExecutor(registry=reg)
    res = ex.execute("daily_health", dry_run=True, trade_date="2026-04-30")
    assert res.success is True
    assert res.task_id == "daily_health"
    assert res.dependency_execution_order == ["daily_health"]
    assert len(res.steps) == len(reg.tasks["daily_health"].steps)
    for s in res.steps:
        assert s.ok is True
        assert s.output.get("dry_run") is True


def test_unified_after_close_dry_run(tmp_path: Path):
    # 生产 Registry 中 unified_after_close 仍为 enabled:false；dry-run 拓扑用临时启用副本验证
    p = tmp_path / "tasks_registry.yaml"
    p.write_text(
        """
version: "1"
orchestrator:
  enabled: true
defaults: {}
tasks:
  - id: unified_after_close
    enabled: true
    steps:
      - id: prediction_verification
        kind: tool
        tool: tool_get_yesterday_prediction_review
        params: {}
        continue_on_failure: true
        timeout_seconds: 600
""",
        encoding="utf-8",
    )
    reg = load_tasks_registry(p)
    ex = DAGExecutor(registry=reg)
    res = ex.execute("unified_after_close", dry_run=True, trade_date="2026-04-30")
    assert res.success is True
    assert len(res.steps) == len(reg.tasks["unified_after_close"].steps)
    assert res.steps[0].step_id == "prediction_verification"
