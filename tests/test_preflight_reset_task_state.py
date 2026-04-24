from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "preflight_reset_task_state_if_ran_today",
    ROOT / "scripts" / "preflight_reset_task_state_if_ran_today.py",
)
assert _spec and _spec.loader
_preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_preflight)
should_remove_state = _preflight.should_remove_state


def test_should_remove_state_succeeded_same_day() -> None:
    st = {
        "state": "succeeded",
        "trade_date": "2026-04-24",
        "trigger_window": "intraday-30m",
    }
    ok, _ = should_remove_state(st, trade_date="2026-04-24", trigger_window="intraday-30m")
    assert ok is True


def test_should_remove_state_succeeded_same_day_nightly_daily() -> None:
    st = {"state": "succeeded", "trade_date": "2026-04-24", "trigger_window": "daily"}
    ok, _ = should_remove_state(st, trade_date="2026-04-24", trigger_window="daily")
    assert ok is True


def test_should_remove_state_wrong_window() -> None:
    st = {
        "state": "succeeded",
        "trade_date": "2026-04-24",
        "trigger_window": "daily",
    }
    ok, reason = should_remove_state(st, trade_date="2026-04-24", trigger_window="intraday-30m")
    assert ok is False
    assert reason == "trigger_window_mismatch"


def test_should_remove_state_failed() -> None:
    st = {"state": "failed", "trade_date": "2026-04-24", "trigger_window": "intraday-30m"}
    ok, reason = should_remove_state(st, trade_date="2026-04-24", trigger_window="intraday-30m")
    assert ok is False
    assert reason == "state_not_succeeded"


def test_should_remove_state_missing_trigger_window_treated_as_match() -> None:
    st = {"state": "succeeded", "trade_date": "2026-04-24"}
    ok, _ = should_remove_state(st, trade_date="2026-04-24", trigger_window="intraday-30m")
    assert ok is True


@pytest.mark.parametrize(
    "payload,expect_removed",
    [
        (
            {
                "state": "succeeded",
                "trade_date": "2026-04-24",
                "trigger_window": "intraday-30m",
            },
            True,
        ),
        ({"state": "running", "trade_date": "2026-04-24", "trigger_window": "intraday-30m"}, False),
    ],
)
def test_script_subprocess(tmp_path: Path, payload: dict, expect_removed: bool) -> None:
    state_dir = tmp_path / "data" / "state"
    state_dir.mkdir(parents=True)
    p = state_dir / "intraday-tail-screening.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "preflight_reset_task_state_if_ran_today.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            "intraday-tail-screening",
            "--trade-date",
            "2026-04-24",
            "--trigger-window",
            "intraday-30m",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip())
    assert out["success"] is True
    if expect_removed:
        assert out["action"] == "removed_state_file"
        assert not p.is_file()
    else:
        assert out["action"] == "noop"
        assert p.is_file()


def test_script_subprocess_nightly_removed(tmp_path: Path) -> None:
    state_dir = tmp_path / "data" / "state"
    state_dir.mkdir(parents=True)
    p = state_dir / "nightly-stock-screening.json"
    p.write_text(
        json.dumps({"state": "succeeded", "trade_date": "2026-04-24", "trigger_window": "daily"}, ensure_ascii=False),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "preflight_reset_task_state_if_ran_today.py"),
            "--root",
            str(tmp_path),
            "--task-id",
            "nightly-stock-screening",
            "--trade-date",
            "2026-04-24",
            "--trigger-window",
            "daily",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip())
    assert out["success"] is True
    assert out["action"] == "removed_state_file"
    assert not p.is_file()
