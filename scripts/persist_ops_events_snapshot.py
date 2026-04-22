#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.chart_console.api.semantic_reader import SemanticReader
from apps.chart_console.api.screening_reader import validate_screening_date_key
from src.data_layer import MetaEnvelope, write_contract_json


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade-date", default="", help="YYYY-MM-DD; default today(UTC)")
    args = ap.parse_args()
    trade_date = (args.trade_date or "").strip() or _today_utc()
    if not validate_screening_date_key(trade_date):
        print(json.dumps({"success": False, "message": "invalid trade_date (use YYYY-MM-DD)"}, ensure_ascii=False))
        return 1
    reader = SemanticReader(ROOT)
    payload = reader.ops_events(trade_date="")
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    quality = str(meta.get("quality_status") or "ok")
    lineage = meta.get("lineage_refs") if isinstance(meta.get("lineage_refs"), list) else []
    out = ROOT / "data" / "semantic" / "ops_events" / f"{trade_date}.json"
    write_contract_json(
        out,
        payload=payload,
        meta=MetaEnvelope(
            schema_name="ops_events_view_v1",
            schema_version="1.0.0",
            task_id="openclaw-jobs-inventory",
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
            data_layer="L4",
            trade_date=trade_date,
            quality_status=quality,
            lineage_refs=[str(x) for x in lineage],
            source_tools=["persist_ops_events_snapshot.py"],
        ),
    )
    print(json.dumps({"success": True, "path": str(out), "trade_date": trade_date}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
