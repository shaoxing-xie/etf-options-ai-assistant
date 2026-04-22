#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FLAGS_PATH = ROOT / "config" / "feature_flags.json"

BATCH2_TASKS = [
    "position-tracking",
    "weekly-selection-review",
    "screening-emergency-stop",
    "extreme-sentiment-monitor",
    "strategy-calibration",
]


def _read_flags() -> dict[str, Any]:
    if not FLAGS_PATH.is_file():
        return {}
    try:
        obj = json.loads(FLAGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _write_flags(obj: dict[str, Any]) -> None:
    FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FLAGS_PATH.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, out.strip()


def main() -> int:
    now = datetime.now(timezone.utc)
    cutoff = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    trade_date = now.strftime("%Y-%m-%d")

    flags_before = _read_flags()
    disabled = set(flags_before.get("legacy_write_disabled_tasks") or [])
    disabled.update(BATCH2_TASKS)
    flags_after = dict(flags_before)
    flags_after["semantic_read_enabled"] = True
    flags_after["legacy_read_enabled"] = False
    flags_after["legacy_write_enabled"] = True
    flags_after["legacy_write_disabled_tasks"] = sorted(disabled)
    _write_flags(flags_after)

    rc_verify, verify_out = _run(
        [
            sys.executable,
            "scripts/verify_legacy_layer_shutdown.py",
            "--paths",
            "data/screening",
            "data/tail_screening",
            "data/watchlist",
            "data/sentiment_check",
            "--files",
            "config/weekly_calibration.json",
            "--since",
            cutoff,
        ]
    )
    try:
        verify_json = json.loads(verify_out)
    except Exception:
        verify_json = {"parse_error": True, "raw": verify_out}

    report = {
        "batch": "batch2-finalize",
        "phase": "phase5-day5",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tasks": BATCH2_TASKS,
        "actions": {
            "cutoff_utc": cutoff,
            "feature_flags_before": flags_before,
            "feature_flags_after": flags_after,
            "flags_path": str(FLAGS_PATH),
            "production_mode": "new_data_layer",
        },
        "verification": {
            "command": f"scripts/verify_legacy_layer_shutdown.py --paths data/screening data/tail_screening data/watchlist data/sentiment_check --files config/weekly_calibration.json --since {cutoff}",
            "exit_code": rc_verify,
            "result": verify_json,
        },
        "pass": rc_verify == 0,
        "notes": [
            "legacy_read_enabled=false 表示线上读取正式切至新数据层。",
            "legacy_write_disabled_tasks 已覆盖第一批+第二批任务。",
            "若后续 OpenClaw 外部流程仍写旧路径，请在 cron/workflow 同步移除旧落盘步骤。",
        ],
    }
    out = ROOT / "data" / "meta" / "shutdown_reports" / f"batch2_finalize_{trade_date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": report["pass"], "report_path": str(out)}, ensure_ascii=False))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
