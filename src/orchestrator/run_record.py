from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.orchestrator.registry import project_root


def write_task_run_v1(
    payload: dict[str, Any],
    *,
    trade_date: str | None = None,
) -> Path:
    """
    落盘 data/semantic/task_runs_v1/{trade_date|unknown}/{run_id}.json
    契约名 task_run_record_v1（在 schema_registry 登记）
    """
    root = project_root()
    now = datetime.now(timezone.utc)
    run_id = str(payload.get("run_id") or f"run_{int(now.timestamp())}")
    td = trade_date or now.strftime("%Y-%m-%d")
    base = root / "data" / "semantic" / "task_runs_v1" / td.replace("-", "_")
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{run_id}.json"
    out = {
        "schema_name": "task_run_record_v1",
        "schema_version": "1.0.0",
        "data_layer": "L4_semantic_ops",
        "run_id": run_id,
        "trade_date": td,
        "generated_at": now.isoformat(),
        "payload": payload,
    }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
