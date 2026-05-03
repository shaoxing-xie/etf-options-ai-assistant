#!/usr/bin/env python3
"""Fail if assistant ``error_codes.yaml`` keys diverge from plugin ``plugins/utils/error_codes.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml


def main() -> int:
    root_a = Path(__file__).resolve().parents[1]
    root_p = root_a.parent / "openclaw-data-china-stock"
    ypath = root_a / "data" / "meta" / "error_codes.yaml"
    pypath = root_p / "plugins" / "utils" / "error_codes.py"
    if not ypath.is_file():
        print("missing", ypath, file=sys.stderr)
        return 2
    if not pypath.is_file():
        print("missing plugin repo at", pypath, file=sys.stderr)
        return 2
    doc = yaml.safe_load(ypath.read_text(encoding="utf-8")) or {}
    yaml_keys = set((doc.get("error_codes") or {}).keys())
    spec = importlib.util.spec_from_file_location("plugin_error_codes", pypath)
    if spec is None or spec.loader is None:
        print("cannot load", pypath, file=sys.stderr)
        return 2
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    py_keys = getattr(mod, "ERROR_CODE_KEYS", set())
    if yaml_keys != py_keys:
        only_yaml = sorted(yaml_keys - py_keys)
        only_py = sorted(py_keys - yaml_keys)
        print("error_codes mismatch:", file=sys.stderr)
        if only_yaml:
            print("  only in YAML:", only_yaml, file=sys.stderr)
        if only_py:
            print("  only in plugin Python:", only_py, file=sys.stderr)
        return 1
    print("error_codes sync OK:", len(yaml_keys), "codes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
