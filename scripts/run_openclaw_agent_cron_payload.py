#!/usr/bin/env python3
"""
Headless OpenClaw agent turn for cron payloads stored on disk (长 message 不经 shell 插值).

由 tasks_registry.cron_jobs.yaml 中 exec 步调用；manifest 由 scripts/sync_cron_to_orchestrator.py 生成。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "cron_agent_payload_manifest.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True, help="OpenClaw cron job id")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    args = ap.parse_args()

    if not args.manifest.exists():
        print(json.dumps({"success": False, "error": f"missing manifest {args.manifest}"}, ensure_ascii=False))
        return 2

    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    row = data.get(args.job_id)
    if not isinstance(row, dict):
        print(json.dumps({"success": False, "error": f"unknown job_id {args.job_id}"}, ensure_ascii=False))
        return 2

    rel = str(row.get("message_file") or "").strip()
    if not rel or ".." in rel.split("/"):
        print(json.dumps({"success": False, "error": f"bad message_file {rel!r}"}, ensure_ascii=False))
        return 2
    msg_path = ROOT / rel
    if not msg_path.is_file():
        print(json.dumps({"success": False, "error": f"missing message file {msg_path}"}, ensure_ascii=False))
        return 2

    message = msg_path.read_text(encoding="utf-8")
    agent = str(row.get("agent_id") or "etf_main").strip()
    timeout_s = int(row.get("timeout_seconds") or 600)
    thinking = str(row.get("thinking") or "off").strip()

    cmd = [
        "openclaw",
        "agent",
        "--local",
        "--agent",
        agent,
        "--thinking",
        thinking,
        "--timeout",
        str(timeout_s),
        "--message",
        message,
    ]
    proc = subprocess.run(cmd, cwd=str(Path.home()), capture_output=True, text=True)
    ok = proc.returncode == 0
    tail = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-4000:]
    print(json.dumps({"success": ok, "exit_code": proc.returncode, "tail": tail}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
