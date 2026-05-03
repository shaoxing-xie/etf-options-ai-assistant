#!/usr/bin/env python3
"""Inventory direct imports of common CN market SDKs (Phase 3 / quarterly audit).

Walks Python files under the assistant repo root, skips virtualenvs and backup
trees, and reports lines matching ``akshare`` / ``tushare`` / ``baostock`` import
patterns (same intent as the manual ``rg`` one-liner in
``docs/data_layer_direct_imports_backlog.md``).

Always exits 0 (reporting tool). Use in CI for visibility only.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

# Repo root: scripts/ -> parent
ROOT = Path(__file__).resolve().parents[1]

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "__pycache__",
        "node_modules",
        ".recovery_backups",
        "build",
        "dist",
        ".eggs",
    }
)

# Line-level: import X / from X — avoid matching strings in comments poorly (acceptable false positives rare)
LINE_RES: list[tuple[str, re.Pattern[str]]] = [
    ("akshare", re.compile(r"^\s*(?:import|from)\s+akshare\b")),
    ("tushare", re.compile(r"^\s*(?:import|from)\s+tushare\b")),
    ("baostock", re.compile(r"^\s*(?:import|from)\s+baostock\b")),
]


def _skip_dir(name: str) -> bool:
    if name in SKIP_DIR_NAMES:
        return True
    return name.endswith(".egg-info")


def scan(root: Path) -> dict[str, list[tuple[Path, int, str]]]:
    hits: dict[str, list[tuple[Path, int, str]]] = defaultdict(list)
    for path in root.rglob("*.py"):
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(_skip_dir(p) for p in rel.parts):
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        # Fast path: skip files that cannot contain our import patterns.
        if (
            b"akshare" not in raw
            and b"tushare" not in raw
            and b"baostock" not in raw
        ):
            continue
        text = raw.decode("utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.rstrip()
            for label, rx in LINE_RES:
                if rx.search(stripped):
                    hits[label].append((path, i, stripped[:200]))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root (default: assistant repo containing scripts/)",
    )
    ap.add_argument(
        "--summary-only",
        action="store_true",
        help="Print one-line summary only (for CI)",
    )
    ap.add_argument(
        "--max-detail",
        type=int,
        default=80,
        help="Max detail lines printed per label when not --summary-only",
    )
    args = ap.parse_args()
    root: Path = args.root.resolve()
    if not root.is_dir():
        print("invalid --root", root, file=sys.stderr)
        return 2

    grouped = scan(root)
    total_hits = sum(len(v) for v in grouped.values())
    files_with_hits = {
        str(p.relative_to(root)) for lst in grouped.values() for p, _, _ in lst
    }

    if args.summary_only:
        print(
            f"direct_connection_scan root={root} "
            f"hits={total_hits} files={len(files_with_hits)} "
            f"by_lib={{{', '.join(f'{k}:{len(v)}' for k, v in sorted(grouped.items()))}}}"
        )
        return 0

    print(f"# Direct connection import scan\n# root: {root}\n")
    print(f"total_hits={total_hits} distinct_files={len(files_with_hits)}\n")
    for label in sorted(grouped.keys()):
        lst = grouped[label]
        print(f"## {label} ({len(lst)})\n")
        for path, lineno, snippet in lst[: args.max_detail]:
            rel = path.relative_to(root)
            print(f"- `{rel}:{lineno}`: {snippet}")
        if len(lst) > args.max_detail:
            print(f"- ... {len(lst) - args.max_detail} more")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
