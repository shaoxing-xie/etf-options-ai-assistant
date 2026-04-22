#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_layer import MetaEnvelope, append_contract_jsonl, write_contract_json


def _now_trade_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _run_id(task_id: str) -> str:
    return f"{task_id}.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"


def migrate_pre_market_sentiment_check(trade_date: str) -> Path:
    src = ROOT / "data" / "sentiment_check" / f"{trade_date}.json"
    payload = _read_json(src) or {}
    out = ROOT / "data" / "semantic" / "dashboard_snapshot" / f"{trade_date}.json"
    return write_contract_json(
        out,
        payload=payload,
        meta=MetaEnvelope(
            schema_name="sentiment_snapshot_v1",
            schema_version="1.0.0",
            task_id="pre-market-sentiment-check",
            run_id=_run_id("pre-market-sentiment-check"),
            data_layer="L4",
            trade_date=trade_date,
            quality_status="degraded" if bool(payload.get("degraded")) else "ok",
            lineage_refs=[str(src)],
            source_tools=["migrate_task_outputs_to_new_layer.py"],
        ),
    )


def migrate_strategy_calibration(trade_date: str) -> Path:
    src = ROOT / "config" / "weekly_calibration.json"
    payload = _read_json(src) or {}
    out = ROOT / "data" / "decisions" / "signals" / f"strategy_calibration_{trade_date}.json"
    return write_contract_json(
        out,
        payload=payload,
        meta=MetaEnvelope(
            schema_name="watchlist_state_v1",
            schema_version="1.0.0",
            task_id="strategy-calibration",
            run_id=_run_id("strategy-calibration"),
            data_layer="L3",
            trade_date=trade_date,
            quality_status="ok",
            lineage_refs=[str(src)],
            source_tools=["migrate_task_outputs_to_new_layer.py"],
        ),
    )


def migrate_nightly_stock_screening(trade_date: str) -> Path:
    src = ROOT / "data" / "screening" / f"{trade_date}.json"
    payload = _read_json(src) or {}
    out = ROOT / "data" / "decisions" / "recommendations" / f"nightly_{trade_date}.json"
    return write_contract_json(
        out,
        payload=payload,
        meta=MetaEnvelope(
            schema_name="screening_candidates_v1",
            schema_version="1.0.0",
            task_id="nightly-stock-screening",
            run_id=_run_id("nightly-stock-screening"),
            data_layer="L3",
            trade_date=trade_date,
            quality_status="ok" if payload else "error",
            lineage_refs=[str(src)],
            source_tools=["migrate_task_outputs_to_new_layer.py"],
        ),
    )


def migrate_intraday_tail_screening(trade_date: str) -> Path:
    src = ROOT / "data" / "tail_screening" / f"{trade_date}.json"
    payload = _read_json(src) or _read_json(ROOT / "data" / "tail_screening" / "latest.json") or {}
    out = ROOT / "data" / "decisions" / "recommendations" / f"tail_{trade_date}.json"
    written = write_contract_json(
        out,
        payload=payload,
        meta=MetaEnvelope(
            schema_name="tail_recommendations_v1",
            schema_version="1.0.0",
            task_id="intraday-tail-screening",
            run_id=_run_id("intraday-tail-screening"),
            data_layer="L3",
            trade_date=trade_date,
            quality_status="ok" if payload else "error",
            lineage_refs=[str(src)],
            source_tools=["migrate_task_outputs_to_new_layer.py"],
        ),
    )
    append_contract_jsonl(
        ROOT / "data" / "semantic" / "timeline_feed" / f"{trade_date}.jsonl",
        payload={
            "event_id": f"intraday-tail-screening.{trade_date}",
            "event_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event_type": "tail_recommendation",
            "summary": f"migrated tail screening for {trade_date}",
        },
        meta=MetaEnvelope(
            schema_name="timeline_event_v1",
            schema_version="1.0.0",
            task_id="intraday-tail-screening",
            run_id=_run_id("intraday-tail-screening"),
            data_layer="L4",
            trade_date=trade_date,
            quality_status="ok" if payload else "error",
            lineage_refs=[str(written)],
            source_tools=["migrate_task_outputs_to_new_layer.py"],
        ),
    )
    return written


def migrate_position_tracking(trade_date: str) -> Path:
    src = ROOT / "data" / "watchlist" / "default.json"
    payload = _read_json(src) or {"symbols": []}
    out = ROOT / "data" / "decisions" / "watchlist" / "history" / f"{trade_date}.json"
    return write_contract_json(
        out,
        payload=payload,
        meta=MetaEnvelope(
            schema_name="watchlist_state_v1",
            schema_version="1.0.0",
            task_id="position-tracking",
            run_id=_run_id("position-tracking"),
            data_layer="L3",
            trade_date=trade_date,
            quality_status="ok",
            lineage_refs=[str(src)],
            source_tools=["migrate_task_outputs_to_new_layer.py"],
        ),
    )


def migrate_weekly_selection_review(trade_date: str) -> Path:
    src = ROOT / "data" / "screening" / "weekly_review.json"
    payload = _read_json(src) or {"metrics": {}, "note": "weekly_review missing"}
    week_key = datetime.now(timezone.utc).strftime("%Y-W%V")
    out = ROOT / "data" / "decisions" / "performance" / f"weekly_{week_key}.json"
    return write_contract_json(
        out,
        payload=payload,
        meta=MetaEnvelope(
            schema_name="watchlist_state_v1",
            schema_version="1.0.0",
            task_id="weekly-selection-review",
            run_id=_run_id("weekly-selection-review"),
            data_layer="L3",
            trade_date=trade_date,
            quality_status="ok" if payload.get("metrics") else "degraded",
            lineage_refs=[str(src)],
            source_tools=["migrate_task_outputs_to_new_layer.py"],
        ),
    )


def migrate_screening_emergency_stop(trade_date: str) -> Path:
    src = ROOT / "data" / "screening" / "emergency_pause.json"
    payload = _read_json(src) or {"active": False}
    out = ROOT / "data" / "decisions" / "risk" / "gate_events" / f"{trade_date}.json"
    return write_contract_json(
        out,
        payload={"event_type": "screening_emergency_stop", "payload": payload},
        meta=MetaEnvelope(
            schema_name="timeline_event_v1",
            schema_version="1.0.0",
            task_id="screening-emergency-stop",
            run_id=_run_id("screening-emergency-stop"),
            data_layer="L3",
            trade_date=trade_date,
            quality_status="ok",
            lineage_refs=[str(src)],
            source_tools=["migrate_task_outputs_to_new_layer.py"],
        ),
    )


def migrate_extreme_sentiment_monitor(trade_date: str) -> Path:
    src = ROOT / "data" / "sentiment_check" / f"{trade_date}.json"
    payload = _read_json(src) or {}
    out = ROOT / "data" / "decisions" / "risk" / "gate_events" / f"extreme_sentiment_{trade_date}.json"
    return write_contract_json(
        out,
        payload={"event_type": "extreme_sentiment_monitor", "payload": payload},
        meta=MetaEnvelope(
            schema_name="timeline_event_v1",
            schema_version="1.0.0",
            task_id="extreme-sentiment-monitor",
            run_id=_run_id("extreme-sentiment-monitor"),
            data_layer="L3",
            trade_date=trade_date,
            quality_status="degraded" if bool(payload.get("degraded")) else "ok",
            lineage_refs=[str(src)],
            source_tools=["migrate_task_outputs_to_new_layer.py"],
        ),
    )


TASK_HANDLERS = {
    "pre-market-sentiment-check": migrate_pre_market_sentiment_check,
    "strategy-calibration": migrate_strategy_calibration,
    "nightly-stock-screening": migrate_nightly_stock_screening,
    "intraday-tail-screening": migrate_intraday_tail_screening,
    "position-tracking": migrate_position_tracking,
    "weekly-selection-review": migrate_weekly_selection_review,
    "screening-emergency-stop": migrate_screening_emergency_stop,
    "extreme-sentiment-monitor": migrate_extreme_sentiment_monitor,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", default="all", help="single task id or 'all'")
    ap.add_argument("--trade-date", default=_now_trade_date(), help="YYYY-MM-DD")
    args = ap.parse_args()
    trade_date = str(args.trade_date)

    task_ids = list(TASK_HANDLERS.keys()) if args.task_id == "all" else [str(args.task_id)]
    output: dict[str, Any] = {"success": True, "trade_date": trade_date, "tasks": {}}
    for tid in task_ids:
        handler = TASK_HANDLERS.get(tid)
        if handler is None:
            output["tasks"][tid] = {"success": False, "error": "unknown task"}
            output["success"] = False
            continue
        try:
            path = handler(trade_date)
            output["tasks"][tid] = {"success": True, "output": str(path)}
        except Exception as e:  # noqa: BLE001
            output["tasks"][tid] = {"success": False, "error": f"{type(e).__name__}: {e}"}
            output["success"] = False
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
