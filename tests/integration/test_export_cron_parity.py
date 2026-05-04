"""export_orchestrator_cron_parity：对临时 jobs.json 冒烟。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_export_parity_json(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "j1",
                        "name": "t",
                        "enabled": True,
                        "schedule": "0 9 * * 1-5",
                        "payload": {
                            "kind": "exec",
                            "command": "cd /x && /x/.venv/bin/python scripts/orchestrator_cli.py run daily_health",
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    script = ROOT / "scripts" / "export_orchestrator_cron_parity.py"
    r = subprocess.run(
        [sys.executable, str(script), "--jobs", str(jobs), "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert len(rows) == 1
    assert rows[0]["references_orchestrator"] is True
