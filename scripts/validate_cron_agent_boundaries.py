#!/usr/bin/env python3
# Usage examples:
#   python scripts/validate_cron_agent_boundaries.py
#   python scripts/validate_cron_agent_boundaries.py --jobs ~/.openclaw/cron/jobs.json
#   python scripts/validate_cron_agent_boundaries.py --include-disabled
#   python scripts/validate_cron_agent_boundaries.py --json

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_BLOCKED_AGENTS = ("etf_main", "etf_analysis_agent")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate cron-agent boundaries: no cron jobs should be assigned to "
            "interaction-only agents."
        )
    )
    parser.add_argument(
        "--jobs",
        default=os.path.expanduser("~/.openclaw/cron/jobs.json"),
        help="Path to cron jobs.json (default: ~/.openclaw/cron/jobs.json)",
    )
    parser.add_argument(
        "--blocked-agent",
        action="append",
        dest="blocked_agents",
        default=None,
        help=(
            "Agent ID that must not own cron jobs. "
            "Can be passed multiple times. Defaults to: "
            + ", ".join(DEFAULT_BLOCKED_AGENTS)
        ),
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Also validate disabled jobs (default: only enabled jobs).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable JSON result.",
    )
    return parser.parse_args()


def load_jobs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"jobs file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError(f"invalid jobs format in: {path}")
    return jobs


def main() -> int:
    args = parse_args()
    jobs_path = Path(args.jobs).expanduser()
    blocked_agents = tuple(args.blocked_agents or DEFAULT_BLOCKED_AGENTS)

    try:
        jobs = load_jobs(jobs_path)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[ERROR] failed to read jobs: {exc}", file=sys.stderr)
        return 2

    violations: list[dict[str, Any]] = []
    checked = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        enabled = bool(job.get("enabled", False))
        if not args.include_disabled and not enabled:
            continue
        checked += 1

        agent_id = str(job.get("agentId", ""))
        if agent_id in blocked_agents:
            violations.append(
                {
                    "id": job.get("id"),
                    "name": job.get("name"),
                    "agentId": agent_id,
                    "enabled": enabled,
                    "schedule": (job.get("schedule") or {}).get("expr"),
                }
            )

    result = {
        "ok": len(violations) == 0,
        "jobs_path": str(jobs_path),
        "blocked_agents": list(blocked_agents),
        "checked_jobs": checked,
        "violations_count": len(violations),
        "violations": violations,
    }

    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"jobs: {result['jobs_path']}")
        print(f"checked_jobs: {checked}")
        print(f"blocked_agents: {', '.join(blocked_agents)}")
        if result["ok"]:
            print("PASS: no cron-agent boundary violations.")
        else:
            print(f"FAIL: {len(violations)} violation(s) found.")
            for item in violations:
                print(
                    "- {id} | {name} | agentId={agentId} | enabled={enabled} | schedule={schedule}".format(
                        **item
                    )
                )

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

