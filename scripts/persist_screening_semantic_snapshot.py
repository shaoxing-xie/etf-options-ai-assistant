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

from apps.chart_console.api.screening_reader import validate_screening_date_key
from src.data_layer import MetaEnvelope, write_contract_json


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    return obj if isinstance(obj, dict) else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade-date", default="", help="YYYY-MM-DD; default today(UTC)")
    args = ap.parse_args()
    trade_date = (args.trade_date or "").strip() or _today_utc()
    if not validate_screening_date_key(trade_date):
        print(json.dumps({"success": False, "message": "invalid trade_date (use YYYY-MM-DD)"}, ensure_ascii=False))
        return 1
    legacy = ROOT / "data" / "screening" / f"{trade_date}.json"
    if not legacy.is_file():
        print(json.dumps({"success": False, "message": f"missing legacy screening artifact: {legacy}"}, ensure_ascii=False))
        return 1
    art = _read_json(legacy)
    screening = art.get("screening") if isinstance(art.get("screening"), dict) else {}
    payload = {
        "run_date": trade_date,
        "candidates": screening.get("data") if isinstance(screening.get("data"), list) else [],
        "summary": {
            "quality_score": screening.get("quality_score"),
            "degraded": screening.get("degraded"),
            "universe": screening.get("universe"),
        },
        "artifact_ref": str(legacy),
    }
    out = ROOT / "data" / "semantic" / "screening_candidates" / f"{trade_date}.json"
    write_contract_json(
        out,
        payload=payload,
        meta=MetaEnvelope(
            schema_name="screening_candidates_v1",
            schema_version="1.0.0",
            task_id="nightly-stock-screening",
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
            data_layer="L4",
            trade_date=trade_date,
            quality_status="degraded" if bool(screening.get("degraded")) else "ok",
            lineage_refs=[str(legacy)],
            source_tools=["persist_screening_semantic_snapshot.py"],
        ),
    )
    print(json.dumps({"success": True, "path": str(out), "trade_date": trade_date}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
