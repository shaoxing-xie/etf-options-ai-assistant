"""tasks_registry.cron_jobs.yaml merges into load_tasks_registry when present."""

from __future__ import annotations

from src.orchestrator.registry import load_tasks_registry, project_root


def test_cron_jobs_yaml_merged():
    root = project_root()
    cron = root / "config" / "tasks_registry.cron_jobs.yaml"
    assert cron.exists(), "expected generated config/tasks_registry.cron_jobs.yaml"
    reg = load_tasks_registry()
    assert "daily_health" in reg.tasks
    assert "cron__quality_backstop_audit" in reg.tasks
    assert reg.tasks["cron__quality_backstop_audit"].steps[0].kind == "exec"
