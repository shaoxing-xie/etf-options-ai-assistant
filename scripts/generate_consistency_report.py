#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _count_rows(v: Any) -> int:
    if isinstance(v, list):
        return len(v)
    return 0


def main() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    legacy_nightly = _read_json(ROOT / "data" / "screening" / f"{today}.json") or {}
    new_nightly = _read_json(ROOT / "data" / "decisions" / "recommendations" / f"nightly_{today}.json") or {}
    legacy_tail = _read_json(ROOT / "data" / "tail_screening" / f"{today}.json") or _read_json(
        ROOT / "data" / "tail_screening" / "latest.json"
    ) or {}
    new_tail = _read_json(ROOT / "data" / "decisions" / "recommendations" / f"tail_{today}.json") or {}

    legacy_nightly_rows = _count_rows(((legacy_nightly.get("screening") or {}).get("data")))
    new_nightly_rows = _count_rows((((new_nightly.get("data") or {}).get("screening") or {}).get("data")))
    legacy_tail_rows = _count_rows(legacy_tail.get("recommended"))
    new_tail_rows = _count_rows(((new_tail.get("data") or {}).get("recommended")))
    diffs = []
    if legacy_nightly_rows != new_nightly_rows:
        diffs.append("nightly_rows")
    if legacy_tail_rows != new_tail_rows:
        diffs.append("tail_rows")
    mismatch_rate = 0.0 if not diffs else min(1.0, len(diffs) / 2.0)
    report = {
        "trade_date": today,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mismatch_rate": mismatch_rate,
        "top_mismatch_fields": diffs,
        "affected_tasks": [
            "nightly-stock-screening" if "nightly_rows" in diffs else None,
            "intraday-tail-screening" if "tail_rows" in diffs else None,
        ],
        "rollback_recommended": mismatch_rate > 0.01,
        "stats": {
            "legacy_nightly_rows": legacy_nightly_rows,
            "new_nightly_rows": new_nightly_rows,
            "legacy_tail_rows": legacy_tail_rows,
            "new_tail_rows": new_tail_rows,
        },
    }
    report["affected_tasks"] = [x for x in report["affected_tasks"] if x]
    out = ROOT / "data" / "meta" / "consistency_report" / f"{today}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "path": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
