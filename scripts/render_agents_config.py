#!/usr/bin/env python3
"""
Usage examples:
  python scripts/render_agents_config.py
  python scripts/render_agents_config.py --apply-jobs
  python scripts/render_agents_config.py --openclaw ~/.openclaw/openclaw.json --jobs ~/.openclaw/cron/jobs.json --apply-jobs
  python scripts/render_agents_config.py --dry-run --json
"""

from __future__ import annotations

import argparse
import copy
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


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _upsert_managed_agents(
    openclaw: dict[str, Any], managed: list[dict[str, Any]]
) -> tuple[int, int]:
    agents = openclaw.setdefault("agents", {}).setdefault("list", [])
    if not isinstance(agents, list):
        raise ValueError("openclaw.json: agents.list must be a list")

    by_id: dict[str, dict[str, Any]] = {
        a.get("id"): a for a in agents if isinstance(a, dict) and isinstance(a.get("id"), str)
    }
    created = 0
    updated = 0
    for entry in managed:
        aid = entry["id"]
        base_id = entry["templateAgentId"]
        if aid in by_id:
            obj = by_id[aid]
            updated += 1
        else:
            base = by_id.get(base_id)
            if not base:
                raise ValueError(f"template agent not found: {base_id}")
            obj = copy.deepcopy(base)
            obj["id"] = aid
            agents.append(obj)
            by_id[aid] = obj
            created += 1
        obj["name"] = entry.get("name", aid)
        if "agentDir" in entry:
            obj["agentDir"] = entry["agentDir"]
        if "requiredSkills" in entry:
            obj["skills"] = list(dict.fromkeys(entry["requiredSkills"]))
        if "requiredTools" in entry:
            obj["tools"] = copy.deepcopy(entry["requiredTools"])

    agents.sort(key=lambda x: str(x.get("id", "")))
    return created, updated


def _apply_job_mapping(
    jobs_doc: dict[str, Any], mapping: dict[str, str]
) -> tuple[int, int]:
    jobs = jobs_doc.get("jobs", [])
    if not isinstance(jobs, list):
        raise ValueError("jobs.json: jobs must be a list")
    changed = 0
    seen = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        jid = job.get("id")
        if jid in mapping:
            seen += 1
            target = mapping[jid]
            if job.get("agentId") != target:
                job["agentId"] = target
                changed += 1
    return changed, seen


def main() -> int:
    parser = argparse.ArgumentParser(description="Render managed cron agents from YAML spec.")
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
    parser.add_argument("--apply-jobs", action="store_true", help="Apply jobAgentMapping into jobs.json.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files.")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON summary.")
    args = parser.parse_args()

    spec_path = Path(args.spec).expanduser()
    openclaw_path = Path(args.openclaw).expanduser()
    jobs_path = Path(args.jobs).expanduser()

    spec = _read_yaml(spec_path)
    managed = spec.get("managedAgents") or []
    if not isinstance(managed, list):
        raise ValueError("spec.managedAgents must be a list")
    mapping = spec.get("jobAgentMapping") or {}
    if not isinstance(mapping, dict):
        raise ValueError("spec.jobAgentMapping must be an object")

    openclaw = _read_json(openclaw_path)
    created, updated = _upsert_managed_agents(openclaw, managed)

    jobs_changed = 0
    jobs_seen = 0
    if args.apply_jobs:
        jobs_doc = _read_json(jobs_path)
        jobs_changed, jobs_seen = _apply_job_mapping(jobs_doc, mapping)
    else:
        jobs_doc = None

    if not args.dry_run:
        _write_json(openclaw_path, openclaw)
        if jobs_doc is not None:
            _write_json(jobs_path, jobs_doc)

    summary = {
        "ok": True,
        "spec": str(spec_path),
        "openclaw": str(openclaw_path),
        "jobs": str(jobs_path) if args.apply_jobs else None,
        "dry_run": args.dry_run,
        "created_agents": created,
        "updated_agents": updated,
        "job_mappings_seen": jobs_seen,
        "job_mappings_changed": jobs_changed,
    }

    if args.json_output:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"render_agents_config: OK (created={created}, updated={updated}, "
            f"job_mappings_changed={jobs_changed}, dry_run={args.dry_run})"
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pylint: disable=broad-except
        print(f"render_agents_config: ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

