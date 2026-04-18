#!/usr/bin/env python3
"""
Check cron jobs.json for single-action tasks missing payload.toolsAllow.

A "single-action task" is detected when:
1) payload.kind == "agentTurn"
2) message contains action constraints like "只调用一次" / "唯一动作" / "唯一动作（硬约束）"
3) Exactly one actionable tool name remains after filtering helper/tooling names

Exit code:
- 0: pass
- 1: violations found
- 2: read/parse/runtime error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SINGLE_ACTION_HINTS = (
    "只调用一次",
    "唯一动作",
    "唯一动作（硬约束）",
    "硬约束：必须执行",
)

IGNORED_TOOLS = {
    "tool_call",
    "tool_check_trading_status",
}

TOOL_RE = re.compile(r"\btool_[A-Za-z0-9_]+\b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate single-action cron jobs have strict payload.toolsAllow."
    )
    parser.add_argument(
        "--jobs",
        default=os.path.expanduser("~/.openclaw/cron/jobs.json"),
        help="Path to cron jobs.json (default: ~/.openclaw/cron/jobs.json)",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Also validate disabled jobs (default: enabled only).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable JSON output.",
    )
    return parser.parse_args()


def load_jobs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"jobs file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError(f"invalid jobs format in: {path}")
    return [j for j in jobs if isinstance(j, dict)]


def extract_action_tools(message: str) -> list[str]:
    raw = TOOL_RE.findall(message or "")
    tools = []
    seen = set()
    for t in raw:
        if t in IGNORED_TOOLS:
            continue
        if t not in seen:
            seen.add(t)
            tools.append(t)
    return tools


def is_single_action_message(message: str) -> bool:
    text = message or ""
    return any(hint in text for hint in SINGLE_ACTION_HINTS)


def main() -> int:
    args = parse_args()
    jobs_path = Path(args.jobs).expanduser()

    try:
        jobs = load_jobs(jobs_path)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[ERROR] failed to read jobs: {exc}", file=sys.stderr)
        return 2

    checked = 0
    candidates = 0
    violations: list[dict[str, Any]] = []

    for job in jobs:
        if job.get("payload", {}).get("kind") != "agentTurn":
            continue
        enabled = bool(job.get("enabled", False))
        if not args.include_disabled and not enabled:
            continue
        checked += 1

        payload = job.get("payload") or {}
        message = str(payload.get("message") or "")
        if not is_single_action_message(message):
            continue

        action_tools = extract_action_tools(message)
        if len(action_tools) != 1:
            continue
        candidates += 1

        expected_tool = action_tools[0]
        tools_allow = payload.get("toolsAllow")
        ok = (
            isinstance(tools_allow, list)
            and len(tools_allow) == 1
            and isinstance(tools_allow[0], str)
            and tools_allow[0] == expected_tool
        )
        if ok:
            continue

        violations.append(
            {
                "id": job.get("id"),
                "name": job.get("name"),
                "enabled": enabled,
                "expected_tool": expected_tool,
                "toolsAllow": tools_allow,
            }
        )

    result = {
        "ok": len(violations) == 0,
        "jobs_path": str(jobs_path),
        "checked_jobs": checked,
        "single_action_candidates": candidates,
        "violations_count": len(violations),
        "violations": violations,
    }

    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"jobs: {result['jobs_path']}")
        print(f"checked_jobs: {checked}")
        print(f"single_action_candidates: {candidates}")
        if result["ok"]:
            print("PASS: all single-action cron jobs have strict toolsAllow.")
        else:
            print(f"FAIL: {len(violations)} violation(s) found.")
            for item in violations:
                print(
                    "- {id} | {name} | expected={expected_tool} | toolsAllow={toolsAllow}".format(
                        **item
                    )
                )

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

