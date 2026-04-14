#!/usr/bin/env python3
"""
Validate workflows/*.yaml: every `tool:` id must exist in config/tools_manifest.yaml.

Run from repo root:
  python scripts/validate_workflows.py

Exit 0 if all tools are registered; 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / "workflows"
MANIFEST_PATH = ROOT / "config" / "tools_manifest.yaml"
EXTERNAL_IDS_PATH = ROOT / "config" / "workflow_external_tool_ids.txt"


def _load_manifest_tool_ids() -> set[str]:
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    ids: set[str] = set()
    for item in data.get("tools") or []:
        tid = item.get("id")
        if isinstance(tid, str):
            ids.add(tid)
    return ids


def _load_external_tool_ids() -> set[str]:
    """Extension-registered tools (e.g. openclaw-data-china-stock) listed in repo."""
    if not EXTERNAL_IDS_PATH.is_file():
        return set()
    out: set[str] = set()
    for line in EXTERNAL_IDS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line)
    return out


def _allowed_tool_ids() -> set[str]:
    return _load_manifest_tool_ids() | _load_external_tool_ids()


def _walk_tools(obj: object) -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "tool" and isinstance(v, str) and v.startswith("tool_"):
                found.append(v)
            else:
                found.extend(_walk_tools(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_walk_tools(item))
    return found


def main() -> int:
    if not MANIFEST_PATH.is_file():
        print(f"validate_workflows: missing {MANIFEST_PATH}", file=sys.stderr)
        return 1

    manifest_ids = _load_manifest_tool_ids()
    external_ids = _load_external_tool_ids()
    tool_ids = manifest_ids | external_ids
    yaml_files = sorted(WORKFLOWS_DIR.glob("*.yaml"))
    errors: list[str] = []

    for path in yaml_files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            errors.append(f"{path.name}: YAML parse error: {e}")
            continue
        if data is None:
            continue
        for tool in _walk_tools(data):
            if tool not in tool_ids:
                errors.append(f"{path.name}: unknown tool `{tool}` (not in tools_manifest)")

    if errors:
        print("validate_workflows: FAIL", file=sys.stderr)
        for line in errors:
            print(line, file=sys.stderr)
        return 1

    print(
        "validate_workflows: OK ("
        f"{len(yaml_files)} workflow YAML file(s), "
        f"{len(manifest_ids)} manifest + {len(external_ids)} external = {len(tool_ids)} allowed tool id(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
