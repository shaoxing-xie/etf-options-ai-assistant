#!/usr/bin/env python3
"""
Every tool listed under agents/*.yaml → agent.tools must appear in the merged allowlist:
  - config/tools_manifest.yaml (option-trading-assistant)
  - config/workflow_external_tool_ids.txt (fetch/read tools documented as extension-only here)
  - optional ~/.openclaw/extensions/openclaw-data-china-stock/config/tools_manifest.yaml
    when present (data_collector_agent lists many tools from that plugin)

Run from repo root:
  python scripts/validate_agent_yaml_tools.py

Usage examples:
  # Validate agents/*.yaml tool allowlist (non-zero exit on mismatch)
  python3 scripts/validate_agent_yaml_tools.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / "agents"
MANIFEST = ROOT / "config" / "tools_manifest.yaml"
EXTERNAL = ROOT / "config" / "workflow_external_tool_ids.txt"
CHINA_STOCK_MANIFEST = Path.home() / ".openclaw" / "extensions" / "openclaw-data-china-stock" / "config" / "tools_manifest.yaml"


def _manifest_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    m = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {t["id"] for t in (m.get("tools") or []) if isinstance(t, dict) and t.get("id")}


def _load_allowed() -> set[str]:
    ids = _manifest_ids(MANIFEST)
    ext: set[str] = set()
    if EXTERNAL.is_file():
        for line in EXTERNAL.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                ext.add(line)
    ids |= ext
    ids |= _manifest_ids(CHINA_STOCK_MANIFEST)
    return ids


def main() -> int:
    allowed = _load_allowed()
    errors: list[str] = []
    for path in sorted(AGENTS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tools = (data.get("agent") or {}).get("tools") or []
        for t in tools:
            if not isinstance(t, str) or not t.startswith("tool_"):
                continue
            if t not in allowed:
                errors.append(f"{path.name}: unknown tool `{t}` (not in manifest + external)")
    if errors:
        print("validate_agent_yaml_tools: FAIL", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print(f"validate_agent_yaml_tools: OK ({len(list(AGENTS_DIR.glob('*.yaml')))} agent YAML file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
