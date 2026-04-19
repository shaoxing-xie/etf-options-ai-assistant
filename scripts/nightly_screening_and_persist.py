#!/usr/bin/env python3
"""
夜盘选股：调用 tool_screen_equity_factors → tool_finalize_screening_nightly（落盘 + 门禁 + 观察池）。

用法（项目根）:
  PYTHONPATH=. python3 scripts/nightly_screening_and_persist.py
  PYTHONPATH=. python3 scripts/nightly_screening_and_persist.py --universe hs300 --top-n 15
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_tool(name: str, args: dict) -> dict:
    exe = sys.executable
    runner = ROOT / "tool_runner.py"
    proc = subprocess.run(
        [exe, str(runner), name, json.dumps(args, ensure_ascii=False)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "tool failed")
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="hs300")
    ap.add_argument("--top-n", type=int, default=15)
    ap.add_argument("--max-universe-size", type=int, default=50)
    args = ap.parse_args()

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    screen = _run_tool(
        "tool_screen_equity_factors",
        {
            "universe": args.universe,
            "regime_hint": "oscillation",
            "top_n": args.top_n,
            "max_universe_size": args.max_universe_size,
            "factors": ["reversal_5d", "fund_flow_3d", "sector_momentum_5d"],
            "neutralize": [],
        },
    )
    fin = _run_tool(
        "tool_finalize_screening_nightly",
        {"screening_result": screen, "attempt_watchlist": True},
    )
    print(json.dumps({"screen": screen.get("success"), "finalize": fin}, ensure_ascii=False, indent=2))
    return 0 if fin.get("success") and screen.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
