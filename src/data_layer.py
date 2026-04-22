from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class MetaEnvelope:
    schema_name: str
    schema_version: str
    task_id: str
    run_id: str
    data_layer: str
    trade_date: str
    quality_status: str = "ok"
    lineage_refs: list[str] | None = None
    source_tools: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "data_layer": self.data_layer,
            "generated_at": utc_now_iso(),
            "trade_date": self.trade_date,
            "quality_status": self.quality_status,
            "lineage_refs": self.lineage_refs or [],
            "source_tools": self.source_tools or [],
        }


def write_contract_json(path: Path, payload: dict[str, Any], meta: MetaEnvelope) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"_meta": meta.as_dict(), "data": payload}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def append_contract_jsonl(path: Path, payload: dict[str, Any], meta: MetaEnvelope) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"_meta": meta.as_dict(), "data": payload}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
