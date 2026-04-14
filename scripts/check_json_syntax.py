#!/usr/bin/env python3
"""Validate JSON syntax for repository JSON files.

Usage examples (run from repo root):
  python3 scripts/check_json_syntax.py
"""

from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".venv_yf",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
}


def should_skip(path: pathlib.Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return any(rel == d or rel.startswith(d + "/") for d in EXCLUDE_DIRS)


def main() -> int:
    failures: list[str] = []
    for p in ROOT.rglob("*.json"):
        if not p.is_file():
            continue
        if should_skip(p):
            continue
        try:
            with p.open("r", encoding="utf-8") as f:
                json.load(f)
        except Exception as exc:
            failures.append(f"{p.relative_to(ROOT).as_posix()}: {exc}")

    if failures:
        print("JSON syntax check failed:")
        for item in failures:
            print(f"- {item}")
        return 1

    print("JSON syntax check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
