#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    p = argparse.ArgumentParser(description="Backfill decision_risk_events jsonl when missing/empty")
    p.add_argument("--trade-date", default=datetime.now().strftime("%Y-%m-%d"))
    p.add_argument("--task-id", default="etf-rotation-research")
    p.add_argument("--run-id", default="", help="Optional run_id; if empty try read from semantic/rotation_latest")
    args = p.parse_args()

    td = str(args.trade_date)
    task_id = str(args.task_id)
    run_id = str(args.run_id).strip()
    generated_at = datetime.now().isoformat()

    risk_path = ROOT / "data" / "decision" / "risk_events" / f"{td}.jsonl"
    cand_path = ROOT / "data" / "decision" / "rotation_candidates" / f"{td}.jsonl"
    sem_path = ROOT / "data" / "semantic" / "rotation_latest" / f"{td}.json"
    risk_path.parent.mkdir(parents=True, exist_ok=True)

    if not run_id and sem_path.is_file():
        try:
            obj = json.loads(sem_path.read_text(encoding="utf-8"))
            meta = obj.get("_meta") if isinstance(obj, dict) else {}
            if isinstance(meta, dict):
                run_id = str(meta.get("run_id") or "").strip()
        except Exception:
            run_id = ""
    if not run_id:
        run_id = datetime.now().strftime("%Y%m%dT%H%M%S")

    existing = risk_path.read_text(encoding="utf-8") if risk_path.is_file() else ""
    if existing.strip():
        print(json.dumps({"success": True, "message": "risk_events already present", "path": str(risk_path)}, ensure_ascii=False))
        return 0

    rec: Dict[str, Any] = {
        "_meta": {
            "schema_name": "decision_risk_events_v1",
            "schema_version": "1.0.0",
            "task_id": task_id,
            "run_id": run_id,
            "data_layer": "L3",
            "generated_at": generated_at,
            "trade_date": td,
            "source_tools": ["backfill_rotation_risk_events"],
            "lineage_refs": [str(cand_path), str(sem_path)],
            "quality_status": "degraded",
        },
        "data": {
            "event_id": f"{task_id}.{run_id}.risk.backfill",
            "event_type": "none",
            "severity": "info",
            "details": {"note": "backfilled placeholder; upstream run emitted no risk events or file was empty"},
        },
    }
    risk_path.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"success": True, "message": "backfilled", "path": str(risk_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

