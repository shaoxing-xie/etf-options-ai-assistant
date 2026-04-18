#!/usr/bin/env python3
"""Project-wide Python syntax/indentation checker."""

from __future__ import annotations

import argparse
import os
import py_compile
import sys
from typing import List, Tuple

DEFAULT_SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".cursor",
    "node_modules",
}


def collect_errors(root: str, skip_dirs: set[str]) -> List[Tuple[str, str]]:
    errors: List[Tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            try:
                py_compile.compile(path, doraise=True)
            except Exception as exc:  # pragma: no cover
                errors.append((path, str(exc)))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Python files for syntax/indentation errors.")
    parser.add_argument("--root", default=".", help="Root directory to scan (default: current directory).")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    errors = collect_errors(root, DEFAULT_SKIP_DIRS)

    print(f"SYNTAX_CHECK_ROOT={root}")
    print(f"TOTAL_ERRORS={len(errors)}")
    if errors:
        for path, err in errors:
            print(f"ERR::{path}::{err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
