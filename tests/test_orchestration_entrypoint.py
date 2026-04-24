from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def orch_mod():
    name = "orch_entrypoint_under_test"
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "orchestration_entrypoint.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_subprocess_exception_calls_finish_failed(orch_mod) -> None:
    """子 shell 未正常返回（异常）时，不得把 state 永久留在 running。"""
    finish_kw: list[dict] = []

    def capture_finish(self, *, to_state, reason, depends_on, condition_met=True):
        finish_kw.append(
            {"to_state": to_state, "reason": reason, "depends_on": depends_on, "condition_met": condition_met}
        )
        return {}

    argv = [
        "orchestration_entrypoint.py",
        "--task-id",
        "orch-smoke-task",
        "--trade-date",
        "2099-03-03",
        "--trigger-source",
        "cron",
        "--trigger-window",
        "daily",
        "--depends-on",
        "",
        "--conditions",
        "",
        "--timeout-seconds",
        "5",
        "--session-type",
        "manual",
        "--command",
        "true",
    ]
    old_argv = sys.argv[:]
    try:
        sys.argv = argv
        with (
            patch.object(orch_mod.TaskStateManager, "claim_execution", return_value=(True, "running")),
            patch.object(orch_mod.TaskStateManager, "finish", capture_finish),
            patch.object(orch_mod.subprocess, "run", side_effect=RuntimeError("simulated_subprocess_failure")),
        ):
            with pytest.raises(RuntimeError, match="simulated_subprocess_failure"):
                orch_mod.main()
    finally:
        sys.argv = old_argv

    assert len(finish_kw) == 1
    assert finish_kw[0]["to_state"] == "failed"
    assert "orchestrator_exception:RuntimeError" in finish_kw[0]["reason"]


def test_subprocess_zero_finishes_succeeded(orch_mod) -> None:
    finish_kw: list[dict] = []

    def capture_finish(self, *, to_state, reason, depends_on, condition_met=True):
        finish_kw.append({"to_state": to_state, "reason": reason})
        return {}

    argv = [
        "orchestration_entrypoint.py",
        "--task-id",
        "orch-smoke-task-2",
        "--trade-date",
        "2099-03-04",
        "--trigger-source",
        "cron",
        "--trigger-window",
        "daily",
        "--depends-on",
        "",
        "--conditions",
        "",
        "--timeout-seconds",
        "5",
        "--session-type",
        "manual",
        "--command",
        "true",
    ]
    old_argv = sys.argv[:]
    try:
        sys.argv = argv
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        with (
            patch.object(orch_mod.TaskStateManager, "claim_execution", return_value=(True, "running")),
            patch.object(orch_mod.TaskStateManager, "finish", capture_finish),
            patch.object(orch_mod.subprocess, "run", return_value=mock_proc),
        ):
            code = orch_mod.main()
    finally:
        sys.argv = old_argv

    assert code == 0
    assert finish_kw == [{"to_state": "succeeded", "reason": "completed"}]
