#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_layer import MetaEnvelope, append_contract_jsonl


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def main() -> int:
    weekly = _read_json(ROOT / "data" / "screening" / "weekly_review.json")
    if not weekly:
        print(json.dumps({"success": False, "message": "weekly review not found"}, ensure_ascii=False))
        return 1
    as_of = str(weekly.get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suggestions = weekly.get("suggestions")
    if not isinstance(suggestions, list):
        suggestions = []
    payload = {
        "event_id": f"weekly-selection-review.{run_id}",
        "event_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trade_date": as_of,
        "task_id": "weekly-selection-review",
        "run_id": run_id,
        "to_state": "succeeded",
        "reason": "feedback_ready",
        "feedback_for": ["factor-evolution-weekly", "strategy-evolution-weekly"],
        "suggestions": suggestions[:20],
        "lineage_refs": [str(ROOT / "data" / "screening" / "weekly_review.json")],
    }
    append_contract_jsonl(
        ROOT / "data" / "decisions" / "orchestration" / "events" / f"{as_of}.jsonl",
        payload=payload,
        meta=MetaEnvelope(
            schema_name="orchestration_event_v1",
            schema_version="1.0.0",
            task_id="weekly-selection-review",
            run_id=run_id,
            data_layer="L3",
            trade_date=as_of,
            quality_status="ok",
            lineage_refs=[str(ROOT / "data" / "screening" / "weekly_review.json")],
            source_tools=["persist_weekly_review_feedback.py"],
        ),
    )
    print(json.dumps({"success": True, "trade_date": as_of, "suggestion_count": len(suggestions)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
