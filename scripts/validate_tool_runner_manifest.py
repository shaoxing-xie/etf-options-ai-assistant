#!/usr/bin/env python3
"""
Ensure every tool id in config/tools_manifest.yaml can be executed by tool_runner.py:
either present in TOOL_MAP, or present in ALIASES with a target that exists in TOOL_MAP.

Run from repo root:
  python scripts/validate_tool_runner_manifest.py

Usage examples:
  # Validate manifest vs tool_runner (non-zero exit on mismatch)
  python3 scripts/validate_tool_runner_manifest.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "tools_manifest.yaml"
RUNNER = ROOT / "tool_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("tool_runner_mod", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {RUNNER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _can_execute(tool_id: str, tm: dict, aliases: dict) -> bool:
    if tool_id in tm:
        return True
    if tool_id in aliases:
        target = aliases[tool_id][0]
        return target in tm
    return False


def main() -> int:
    if not MANIFEST.is_file():
        print(f"validate_tool_runner_manifest: missing {MANIFEST}", file=sys.stderr)
        return 1
    mod = _load_runner()
    tm = getattr(mod, "TOOL_MAP", {})
    aliases = getattr(mod, "ALIASES", {})
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    ids = [t["id"] for t in (data.get("tools") or []) if isinstance(t, dict) and t.get("id")]
    bad = [i for i in ids if not _can_execute(i, tm, aliases)]
    broken = [k for k, v in aliases.items() if v[0] not in tm]
    if broken:
        print("validate_tool_runner_manifest: FAIL (alias target missing from TOOL_MAP)", file=sys.stderr)
        for k in broken:
            print(f"  {k} -> {aliases[k][0]}", file=sys.stderr)
        return 1
    if bad:
        print("validate_tool_runner_manifest: FAIL", file=sys.stderr)
        for i in bad:
            print(f"  manifest tool not executable: {i}", file=sys.stderr)
        return 1
    print(f"validate_tool_runner_manifest: OK ({len(ids)} manifest tool(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
