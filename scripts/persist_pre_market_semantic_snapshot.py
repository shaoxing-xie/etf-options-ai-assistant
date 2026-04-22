#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.data_layer import MetaEnvelope, write_contract_json

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sidecar_dir = ROOT / "data" / "sentiment_check"
    if not sidecar_dir.is_dir():
        print(json.dumps({"success": False, "message": "missing sentiment_check dir"}, ensure_ascii=False))
        return 1
    candidates = sorted([p for p in sidecar_dir.glob("*.json") if p.is_file()])
    if not candidates:
        print(json.dumps({"success": False, "message": "no sentiment sidecar file"}, ensure_ascii=False))
        return 1
    latest = candidates[-1]
    payload = json.loads(latest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        print(json.dumps({"success": False, "message": "invalid sidecar json"}, ensure_ascii=False))
        return 1
    trade_date = latest.stem
    out = ROOT / "data" / "semantic" / "dashboard_snapshot" / f"{trade_date}.json"
    write_contract_json(
        out,
        payload=payload,
        meta=MetaEnvelope(
            schema_name="sentiment_snapshot_v1",
            schema_version="1.0.0",
            task_id="pre-market-sentiment-check",
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
            data_layer="L4",
            trade_date=trade_date,
            quality_status="degraded" if bool(payload.get("degraded")) else "ok",
            lineage_refs=[str(latest)],
            source_tools=["persist_pre_market_semantic_snapshot.py"],
        ),
    )
    print(json.dumps({"success": True, "path": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
