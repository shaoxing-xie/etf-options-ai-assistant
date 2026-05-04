#!/usr/bin/env python3
"""
从 OpenClaw jobs.json 导出与 orchestrator 相关的 cron parity 表（Markdown / JSON）。

不修改 jobs 文件；用于方案 §2.1 / final-qa 对表与归档。

用法:
  python scripts/export_orchestrator_cron_parity.py
  python scripts/export_orchestrator_cron_parity.py --jobs /path/to/jobs.json --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Export orchestrator-related cron jobs as parity table")
    ap.add_argument(
        "--jobs",
        type=Path,
        default=Path.home() / ".openclaw" / "cron" / "jobs.json",
        help="jobs.json 路径",
    )
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非 Markdown")
    args = ap.parse_args()
    if not args.jobs.is_file():
        print(f"jobs file not found: {args.jobs}", file=sys.stderr)
        return 1
    raw = json.loads(args.jobs.read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = []
    for j in raw.get("jobs", []) or []:
        if not isinstance(j, dict):
            continue
        payload = j.get("payload") if isinstance(j.get("payload"), dict) else {}
        cmd = str(payload.get("command") or "")
        msg = str(payload.get("message") or "")
        orch = "orchestrator_cli.py" in cmd or "orchestrator_cli.py" in msg
        sched = j.get("schedule", "")
        if isinstance(sched, dict) and sched.get("kind") == "cron":
            sched_out = f"{sched.get('expr', '')} tz={sched.get('tz', '')}"
        else:
            sched_out = str(sched)

        rows.append(
            {
                "job_id": j.get("id", ""),
                "name": j.get("name", ""),
                "enabled": bool(j.get("enabled", True)),
                "schedule": sched_out,
                "references_orchestrator": orch,
                "payload_kind": str(payload.get("kind") or ""),
            }
        )
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    print("| job_id | name | enabled | schedule | references_orchestrator | kind |")
    print("| --- | --- | --- | --- | --- | --- |")
    for r in rows:
        print(
            f"| {r['job_id']} | {r['name']} | {r['enabled']} | {r['schedule']} | "
            f"{r['references_orchestrator']} | {r['payload_kind']} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
