#!/usr/bin/env python3
"""
Ensure every tool name listed in cron jobs.json payload.toolsAllow exists in config/tools_manifest.json.

OpenClaw option-trading-assistant registers tools only from the manifest (see index.ts);
missing ids cause runtime "Tool … not found" even when tool_runner.py implements them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--jobs",
        default=str(Path.home() / ".openclaw/cron/jobs.json"),
        help="Path to cron jobs.json",
    )
    ap.add_argument(
        "--manifest",
        default="",
        help="Path to tools_manifest.json (default: <repo>/config/tools_manifest.json next to this script)",
    )
    args = ap.parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    manifest_path = Path(args.manifest) if args.manifest else repo_root / "config" / "tools_manifest.json"
    jobs_path = Path(args.jobs).expanduser()

    if not manifest_path.is_file():
        print(f"[verify_tools_manifest_vs_cron] manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    if not jobs_path.is_file():
        print(f"[verify_tools_manifest_vs_cron] jobs not found: {jobs_path}", file=sys.stderr)
        return 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tools = manifest.get("tools") or []
    ids = {t.get("id") for t in tools if isinstance(t, dict) and t.get("id")}

    jobs_payload = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs = jobs_payload.get("jobs") or []
    if not isinstance(jobs, list):
        print("[verify_tools_manifest_vs_cron] invalid jobs.json", file=sys.stderr)
        return 2

    required: set[str] = set()
    for job in jobs:
        if not isinstance(job, dict):
            continue
        payload = job.get("payload") or {}
        ta = payload.get("toolsAllow")
        if not isinstance(ta, list):
            continue
        for x in ta:
            if not isinstance(x, str):
                continue
            name = x.strip()
            # 仅校验主仓 Python 插件工具（tool_*）。exec / fs.* 等由 Gateway 内置，不在 tools_manifest。
            if name.startswith("tool_"):
                required.add(name)

    missing = sorted(required - ids)
    if missing:
        print(
            "[verify_tools_manifest_vs_cron] FAIL: toolsAllow references tools not in manifest:",
            file=sys.stderr,
        )
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        print(f"  manifest: {manifest_path}", file=sys.stderr)
        print(f"  jobs: {jobs_path}", file=sys.stderr)
        return 1

    print(f"[verify_tools_manifest_vs_cron] ok: {len(required)} tool(s) from toolsAllow present in manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
