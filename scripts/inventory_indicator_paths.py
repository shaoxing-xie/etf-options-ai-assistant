#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List
import argparse


ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    "tool_calculate_technical_indicators(",
    "calculate_technical_indicators(",
    "score_engine=\"58\"",
    "score_engine='58'",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory indicator references")
    parser.add_argument(
        "--fail-on-legacy-direct",
        action="store_true",
        help="Fail when legacy tool id appears in guarded execution paths",
    )
    args = parser.parse_args()

    hits: Dict[str, List[str]] = {}
    for path in ROOT.rglob("*.py"):
        if ".venv" in str(path) or "/tests/" in str(path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        marks = [t for t in TARGETS if t in content]
        if marks:
            hits[str(path.relative_to(ROOT))] = marks

    out = ROOT / "artifacts" / "indicator-migration" / "indicator_path_inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(hits, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"inventory written: {out}")
    print(f"files: {len(hits)}")

    if args.fail_on_legacy_direct:
        legacy_pat = re.compile(r"\btool_calculate_technical_indicators\b")
        guarded_paths = [
            ROOT / "workflows",
            ROOT / "agents",
            ROOT / "config" / "tools_manifest.yaml",
            ROOT / "config" / "tools_manifest.json",
            ROOT / "tool_runner.py",
        ]
        violations: List[str] = []
        for gp in guarded_paths:
            if gp.is_file():
                candidates = [gp]
            else:
                candidates = [p for p in gp.rglob("*") if p.suffix in (".yaml", ".yml", ".json", ".py")]
            for p in candidates:
                try:
                    text = p.read_text(encoding="utf-8")
                except Exception:
                    continue
                if legacy_pat.search(text):
                    violations.append(str(p.relative_to(ROOT)))
        if violations:
            print("legacy_direct_refs_detected:")
            for v in sorted(set(violations)):
                print(f"- {v}")
            return 2
        print("legacy_direct_refs_detected: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
