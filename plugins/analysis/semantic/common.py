from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def semantic_meta(
    *,
    schema_name: str,
    schema_version: str,
    task_id: str,
    trade_date: str,
    data_layer: str,
    lineage_refs: List[str],
    quality_status: str,
    confidence: float,
    source_tools: Optional[List[str]] = None,
) -> Dict[str, Any]:
    rid = datetime.now().strftime("%Y%m%dT%H%M%S")
    meta = {
        "schema_name": schema_name,
        "schema_version": schema_version,
        "task_id": task_id,
        "run_id": rid,
        "data_layer": data_layer,
        "generated_at": datetime.now().isoformat(),
        "trade_date": trade_date,
        "lineage_refs": lineage_refs,
        "quality_status": quality_status,
        "confidence": round(float(confidence), 4),
    }
    if source_tools:
        meta["source_tools"] = source_tools
    return meta


def merge_upstream_quality(*flags: Optional[str]) -> str:
    """Collapse ok/degraded/error — any error wins; else any degraded."""
    xs = [str(x or "").strip().lower() for x in flags if x]
    if any(x == "error" for x in xs):
        return "error"
    if any(x == "degraded" for x in xs):
        return "degraded"
    return "ok"


def confidence_from_quality(base: float, q: str) -> float:
    if q == "error":
        return max(0.0, base * 0.25)
    if q == "degraded":
        return max(0.0, base * 0.65)
    return base
