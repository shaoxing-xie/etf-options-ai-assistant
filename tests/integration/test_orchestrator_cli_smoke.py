"""orchestrator_cli 冒烟（仅 list / dry-run）。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_cli_list_rc0():
    cli = ROOT / "scripts" / "orchestrator_cli.py"
    r = subprocess.run(
        [sys.executable, str(cli), "list"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc.get("success") is True
    ids = {x["id"] for x in doc.get("tasks", [])}
    assert "daily_health" in ids


def test_cli_run_daily_health_dry_run_rc0():
    cli = ROOT / "scripts" / "orchestrator_cli.py"
    r = subprocess.run(
        [
            sys.executable,
            str(cli),
            "run",
            "daily_health",
            "--dry-run",
            "--trade-date",
            "2026-04-30",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(r.stdout)
    assert doc.get("success") is True
    assert doc.get("dependency_execution_order") == ["daily_health"]
