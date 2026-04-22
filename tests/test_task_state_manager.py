from __future__ import annotations

import json
from pathlib import Path

from src.orchestration.task_state_manager import TaskStateManager


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_task_state_manager_claim_and_finish(tmp_path: Path) -> None:
    mgr = TaskStateManager(
        root=tmp_path,
        task_id="nightly-stock-screening",
        trade_date="2026-04-22",
        run_id="r1",
        trigger_source="cron",
        trigger_window="daily",
    )
    ok, reason = mgr.claim_execution(depends_on=["pre-market-sentiment-check"])
    assert ok is True
    assert reason == "running"
    state_path = tmp_path / "data" / "state" / "nightly-stock-screening.json"
    assert _read_json(state_path)["state"] == "running"
    mgr.finish(to_state="succeeded", reason="completed", depends_on=["pre-market-sentiment-check"], condition_met=True)
    assert _read_json(state_path)["state"] == "succeeded"


def test_task_state_manager_idempotent_skip(tmp_path: Path) -> None:
    mgr1 = TaskStateManager(
        root=tmp_path,
        task_id="pre-market-sentiment-check",
        trade_date="2026-04-22",
        run_id="r1",
        trigger_source="dependency",
        trigger_window="daily",
    )
    assert mgr1.claim_execution(depends_on=[])[0] is True
    mgr1.finish(to_state="succeeded", reason="completed", depends_on=[], condition_met=True)
    mgr2 = TaskStateManager(
        root=tmp_path,
        task_id="pre-market-sentiment-check",
        trade_date="2026-04-22",
        run_id="r2",
        trigger_source="cron",
        trigger_window="daily",
    )
    ok, reason = mgr2.claim_execution(depends_on=[])
    assert ok is False
    assert reason == "already_executed"
