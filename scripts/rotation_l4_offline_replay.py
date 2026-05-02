#!/usr/bin/env python3
"""
Offline replay helper: read semantic rotation_latest JSON (L4) and print a compact summary.

Not on the production hot path; intended for backtest / audit prep (P2 minimal deliverable).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Print rotation_latest L4 summary for a trade_date.")
    parser.add_argument("--trade-date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--root",
        default="",
        help="Project root (default: parent of scripts/)",
    )
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve() if args.root else Path(__file__).resolve().parents[1]
    path = root / "data" / "semantic" / "rotation_latest" / f"{args.trade_date}.json"
    if not path.is_file():
        print(json.dumps({"ok": False, "message": "file_missing", "path": str(path)}, ensure_ascii=False))
        return 1
    obj = json.loads(path.read_text(encoding="utf-8"))
    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
    unified = data.get("unified_next_day") if isinstance(data.get("unified_next_day"), list) else []
    out = {
        "ok": True,
        "trade_date": data.get("trade_date") or args.trade_date,
        "quality": (data.get("data_quality") or {}).get("quality_status"),
        "unified_rows": len(unified),
        "top_unified": [
            {
                "rank": u.get("rank"),
                "etf_code": u.get("etf_code"),
                "unified_score": u.get("unified_score"),
                "gate_effective": u.get("gate_effective"),
            }
            for u in unified[:8]
            if isinstance(u, dict)
        ],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
