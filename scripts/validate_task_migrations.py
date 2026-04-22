#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _meta_ok(path: Path) -> tuple[bool, str]:
    j = _read_json(path)
    if not isinstance(j, dict):
        return False, "not json object"
    m = j.get("_meta")
    if not isinstance(m, dict):
        return False, "missing _meta"
    required = [
        "schema_name",
        "schema_version",
        "task_id",
        "run_id",
        "data_layer",
        "generated_at",
        "trade_date",
        "quality_status",
        "lineage_refs",
    ]
    miss = [k for k in required if k not in m]
    if miss:
        return False, f"missing meta keys: {miss}"
    return True, "ok"


def main() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week = datetime.now(timezone.utc).strftime("%Y-W%V")
    files = {
        "pre-market-sentiment-check": ROOT / "data" / "semantic" / "dashboard_snapshot" / f"{today}.json",
        "strategy-calibration": ROOT / "data" / "decisions" / "signals" / f"strategy_calibration_{today}.json",
        "nightly-stock-screening": ROOT / "data" / "decisions" / "recommendations" / f"nightly_{today}.json",
        "intraday-tail-screening": ROOT / "data" / "decisions" / "recommendations" / f"tail_{today}.json",
        "position-tracking": ROOT / "data" / "decisions" / "watchlist" / "history" / f"{today}.json",
        "weekly-selection-review": ROOT / "data" / "decisions" / "performance" / f"weekly_{week}.json",
        "screening-emergency-stop": ROOT / "data" / "decisions" / "risk" / "gate_events" / f"{today}.json",
        "extreme-sentiment-monitor": ROOT / "data" / "decisions" / "risk" / "gate_events" / f"extreme_sentiment_{today}.json",
    }
    out: dict[str, Any] = {"success": True, "results": {}}
    for tid, path in files.items():
        if not path.is_file():
            out["results"][tid] = {"success": False, "error": f"missing file: {path}"}
            out["success"] = False
            continue
        ok, msg = _meta_ok(path)
        out["results"][tid] = {"success": ok, "file": str(path), "check": msg}
        if not ok:
            out["success"] = False
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
