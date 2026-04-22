#!/usr/bin/env python3
from __future__ import annotations

import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-status", default="success", choices=["success", "failed"])
    ap.add_argument("--failure-stage", default="")
    ap.add_argument("--failure-reason", default="")
    args = ap.parse_args()

    trade_date = _today_utc()
    consistency = ROOT / "data" / "meta" / "consistency_report" / f"{trade_date}.json"
    shutdown = ROOT / "data" / "meta" / "shutdown_reports" / f"batch2_finalize_{trade_date}.json"
    jobs_inventory = ROOT / "data" / "meta" / f"openclaw_jobs_inventory_{trade_date}.json"
    ops_snapshot = ROOT / "data" / "semantic" / "ops_events" / f"{trade_date}.json"

    shutdown_obj = _read_json(shutdown) or {}
    shutdown_exit_raw = ((shutdown_obj.get("verification") or {}).get("exit_code"))
    shutdown_exit = int(shutdown_exit_raw) if isinstance(shutdown_exit_raw, int) else 1
    shutdown_pass = bool(shutdown_obj.get("pass")) and shutdown_exit == 0
    ops_obj = _read_json(ops_snapshot) or {}
    ops_meta = ops_obj.get("_meta") if isinstance(ops_obj.get("_meta"), dict) else {}
    ops_data = ops_obj.get("data") if isinstance(ops_obj.get("data"), dict) else {}
    exec_rows = ops_data.get("execution_audit_events") if isinstance(ops_data.get("execution_audit_events"), list) else []
    collect_rows = ops_data.get("collection_quality_events") if isinstance(ops_data.get("collection_quality_events"), list) else []

    evidence = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_status": args.run_status,
        "failure_stage": args.failure_stage or None,
        "failure_reason": args.failure_reason or None,
        "scope": {
            "phase": "Phase2+Batch2",
            "mode": "fast_cutover",
            "observe_days": 1,
            "rollback_window_days": 7,
        },
        "artifacts": {
            "consistency_report": str(consistency.relative_to(ROOT)),
            "shutdown_report": str(shutdown.relative_to(ROOT)),
            "jobs_inventory": str(jobs_inventory.relative_to(ROOT)),
            "ops_events_snapshot": str(ops_snapshot.relative_to(ROOT)),
            "feature_flags": "config/feature_flags.json",
        },
        "checks": {
            "pytest": "tests/test_semantic_reader.py + tests/test_chart_console_screening_reader.py",
            "semantic_api_smoke": [
                "GET /api/semantic/dashboard",
                "GET /api/semantic/timeline?trade_date=YYYY-MM-DD",
                "GET /api/semantic/screening_view?trade_date=YYYY-MM-DD",
                "GET /api/semantic/ops_events?trade_date=YYYY-MM-DD",
            ],
            "legacy_shutdown": {
                "ok": shutdown_pass,
                "exit_code": shutdown_exit,
            },
            "ops_snapshot_contract": {
                "ok": bool(ops_obj) and ops_meta.get("schema_name") == "ops_events_view_v1",
                "schema_name": ops_meta.get("schema_name"),
                "schema_version": ops_meta.get("schema_version"),
                "trade_date": ops_meta.get("trade_date"),
                "execution_rows": len(exec_rows),
                "collection_rows": len(collect_rows),
            },
        },
        "notes": [
            "Batch2 扩展任务（report_sender/data_cache_job）已纳入 L4 语义层（ops_events_view_v1）并支持按交易日回放。",
            "ops-events-semantic-snapshot cron 负责每日沉淀 data/semantic/ops_events/YYYY-MM-DD.json。",
        ],
    }

    out = ROOT / "data" / "meta" / "evidence" / f"batch2_evidence_{trade_date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "path": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
