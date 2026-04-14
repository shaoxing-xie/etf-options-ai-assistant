#!/usr/bin/env python3
"""
Usage examples:
  python scripts/validate_agent_skill_matrix.py
  python scripts/validate_agent_skill_matrix.py --json
  python scripts/validate_agent_skill_matrix.py --openclaw ~/.openclaw/openclaw.json --jobs ~/.openclaw/cron/jobs.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "config" / "agents" / "cron_agents.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"invalid YAML object: {path}")
    return data


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate cron agent/skill/job matrix.")
    parser.add_argument("--spec", default=str(DEFAULT_SPEC), help="Path to cron agent spec YAML.")
    parser.add_argument(
        "--openclaw",
        default=os.path.expanduser("~/.openclaw/openclaw.json"),
        help="Path to openclaw.json",
    )
    parser.add_argument(
        "--jobs",
        default=os.path.expanduser("~/.openclaw/cron/jobs.json"),
        help="Path to cron jobs.json",
    )
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON summary.")
    args = parser.parse_args()

    spec = _read_yaml(Path(args.spec).expanduser())
    openclaw = _read_json(Path(args.openclaw).expanduser())
    jobs_doc = _read_json(Path(args.jobs).expanduser())

    managed = spec.get("managedAgents") or []
    blocked = set(spec.get("blockedCronAgents") or [])
    mapping = spec.get("jobAgentMapping") or {}

    errors: list[str] = []

    agents = openclaw.get("agents", {}).get("list", [])
    if not isinstance(agents, list):
        errors.append("openclaw.json: agents.list is not a list")
        agents = []
    agents_by_id = {
        a.get("id"): a for a in agents if isinstance(a, dict) and isinstance(a.get("id"), str)
    }

    # Validate managed agent definitions + required skills.
    for m in managed:
        aid = m.get("id")
        if not isinstance(aid, str):
            errors.append("spec managedAgents entry missing id")
            continue
        agent = agents_by_id.get(aid)
        if not agent:
            errors.append(f"missing managed agent in openclaw.json: {aid}")
            continue
        required = set(m.get("requiredSkills") or [])
        actual = set(agent.get("skills") or [])
        missing = sorted(required - actual)
        if missing:
            errors.append(f"{aid}: missing required skills: {', '.join(missing)}")
        if "requiredTools" in m:
            expected_tools = m.get("requiredTools")
            actual_tools = agent.get("tools")
            if actual_tools != expected_tools:
                errors.append(f"{aid}: tools mismatch with requiredTools in spec")

    # Validate job mapping and blocked agent boundaries.
    jobs = jobs_doc.get("jobs", [])
    if not isinstance(jobs, list):
        errors.append("jobs.json: jobs is not a list")
        jobs = []

    for job in jobs:
        if not isinstance(job, dict):
            continue
        jid = job.get("id")
        aid = job.get("agentId")
        enabled = bool(job.get("enabled", False))
        if enabled and aid in blocked:
            errors.append(f"{jid}: enabled job bound to blocked agent {aid}")
        target = mapping.get(jid)
        if target and aid != target:
            errors.append(f"{jid}: expected agentId={target}, found {aid}")

    result = {"ok": not errors, "errors": errors, "error_count": len(errors)}
    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            print("validate_agent_skill_matrix: PASS")
        else:
            print(f"validate_agent_skill_matrix: FAIL ({len(errors)} issue(s))", file=sys.stderr)
            for line in errors:
                print(f"- {line}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pylint: disable=broad-except
        print(f"validate_agent_skill_matrix: ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

