#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_layer import MetaEnvelope, write_contract_json
from src.orchestration.task_state_manager import TaskStateManager


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def main() -> int:
    trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    depends_on: list[str] = []
    session_type = str(os.environ.get("ORCH_SESSION_TYPE") or "").strip().lower()
    is_manual_session = session_type == "manual"

    mgr = TaskStateManager(
        root=ROOT,
        task_id="extreme-sentiment-monitor",
        trade_date=trade_date,
        run_id=run_id,
        trigger_source=str(os.environ.get("ORCH_TRIGGER_SOURCE") or "cron").strip().lower(),
        trigger_window="intraday-15m",
    )
    claimed, reason = mgr.claim_execution(depends_on=depends_on)
    if not claimed:
        print(json.dumps({"success": True, "message": reason, "trade_date": trade_date}, ensure_ascii=False))
        return 0

    if not is_manual_session:
        wait = mgr.wait_for_dependencies(depends_on, timeout_seconds=60, poll_seconds=1.0)
        if not wait.satisfied:
            mgr.finish(to_state="skipped", reason=wait.reason, depends_on=depends_on, condition_met=False)
            print(json.dumps({"success": True, "message": wait.reason, "missing": wait.missing}, ensure_ascii=False))
            return 0

    snap = _read_json(ROOT / "data" / "sentiment_check" / f"{trade_date}.json")
    score = snap.get("overall_score")
    stage = str(snap.get("sentiment_stage") or "")
    degraded = bool(snap.get("degraded"))

    is_extreme = False
    try:
        if isinstance(score, (int, float)) and (float(score) >= 85 or float(score) <= 20):
            is_extreme = True
    except Exception:
        pass
    if any(x in stage for x in ("冰点", "退潮", "极端")):
        is_extreme = True

    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "score": score,
        "sentiment_stage": stage,
        "extreme": is_extreme,
        "degraded": degraded,
        "reason": "extreme" if is_extreme else "normal",
    }

    out = ROOT / "data" / "decisions" / "risk" / "gate_events" / f"extreme_sentiment_{trade_date}.json"
    write_contract_json(
        out,
        payload={"event_type": "extreme_sentiment_monitor", "payload": payload},
        meta=MetaEnvelope(
            schema_name="risk_gate_event_v1",
            schema_version="1.0.0",
            task_id="extreme-sentiment-monitor",
            run_id=run_id,
            data_layer="L3",
            trade_date=trade_date,
            quality_status="degraded" if degraded else "ok",
            lineage_refs=[f"data/sentiment_check/{trade_date}.json"],
            source_tools=["extreme_sentiment_monitor_and_persist.py"],
        ),
    )
    mgr.finish(to_state="succeeded", reason="completed", depends_on=depends_on, condition_met=True)
    print(json.dumps({"success": True, "trade_date": trade_date, "extreme": is_extreme}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
