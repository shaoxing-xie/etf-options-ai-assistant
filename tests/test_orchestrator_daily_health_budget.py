"""daily_health 步骤超时与 Cron yieldMs 预算对齐（最优：避免 agent/exec 过早杀进程）。"""

from __future__ import annotations

from src.orchestrator.registry import load_tasks_registry


def test_daily_health_sum_of_step_timeouts():
    reg = load_tasks_registry()
    dh = reg.tasks["daily_health"]
    secs = [int(s.timeout_seconds or 0) for s in dh.steps]
    assert sum(secs) == 1200  # 180+120+900，Cron yieldMs 应显著大于此值


def test_registry_default_task_timeout_covers_daily_health():
    reg = load_tasks_registry()
    assert int(reg.defaults.get("timeout_seconds") or 0) >= 1200
