#!/usr/bin/env python3
"""Validate merged runtime config has required top-level keys (JSON Schema required list)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import load_system_config  # noqa: E402
from src.config_validate import missing_runtime_surface_keys  # noqa: E402


def main() -> int:
    schema_path = ROOT / "config" / "schema" / "runtime_surface.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    required = list(schema.get("required") or [])
    if not required:
        print("schema missing required array", file=sys.stderr)
        return 2
    cfg = load_system_config(use_cache=False)
    missing = missing_runtime_surface_keys(cfg, schema_path=schema_path)
    if missing:
        print(f"missing top-level keys: {missing}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
