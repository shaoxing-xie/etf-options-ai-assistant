#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def _read(path: str) -> Dict[str, Any]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def _symbols(data: Dict[str, Any]) -> List[str]:
    rows = data.get("top10") if isinstance(data.get("top10"), list) else []
    return [str(r.get("symbol")) for r in rows if isinstance(r, dict) and r.get("symbol")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two indicator migration snapshots")
    parser.add_argument("--base", required=True, help="Baseline JSON")
    parser.add_argument("--new", required=True, help="New JSON")
    parser.add_argument("--min-top10-overlap-pct", type=float, default=95.0)
    parser.add_argument("--max-duration-regression-pct", type=float, default=0.0)
    parser.add_argument("--enforce-gate", action="store_true")
    args = parser.parse_args()

    b = _read(args.base)
    n = _read(args.new)

    b_sym = _symbols(b)
    n_sym = _symbols(n)
    overlap = len(set(b_sym) & set(n_sym))
    ratio = (overlap / max(1, len(set(b_sym)))) * 100.0
    b_dur = float(b.get("duration_ms") or 0.0)
    n_dur = float(n.get("duration_ms") or 0.0)
    dur_reg = ((n_dur - b_dur) / b_dur * 100.0) if b_dur > 0 else 0.0
    pass_overlap = ratio >= float(args.min_top10_overlap_pct)
    pass_perf = dur_reg <= float(args.max_duration_regression_pct)
    gate_pass = pass_overlap and pass_perf

    print("indicator migration compare")
    print(f"- base_duration_ms: {b_dur:.0f}")
    print(f"- new_duration_ms: {n_dur:.0f}")
    print(f"- duration_regression_pct: {dur_reg:.2f}%")
    print(f"- top10_overlap: {overlap}/10 ({ratio:.2f}%)")
    print(f"- base_top3: {b_sym[:3]}")
    print(f"- new_top3:  {n_sym[:3]}")
    print(
        f"- gate(min_overlap={args.min_top10_overlap_pct:.2f}%, max_regression={args.max_duration_regression_pct:.2f}%): "
        f"{'PASS' if gate_pass else 'FAIL'}"
    )
    if args.enforce_gate and not gate_pass:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
