"""
Trading Journal (JSONL event log).

Why:
- Provide an append-only, schema-stable, low-friction audit trail for signals/positions/reviews.
- Works alongside existing JSON-per-day + SQLite in strategy_tracker, without breaking compatibility.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz


@dataclass(frozen=True)
class JournalConfig:
    # default under project data/
    dir_name: str = "data/trading_journal"
    file_name: str = "events.jsonl"
    schema_version: str = "trading_journal.v1"


def _now_iso_cn() -> str:
    tz = pytz.timezone("Asia/Shanghai")
    return datetime.now(tz).isoformat()


def _journal_path(base_dir: Optional[Path] = None, cfg: JournalConfig = JournalConfig()) -> Path:
    if base_dir is None:
        # src/.. = project root
        base_dir = Path(__file__).resolve().parents[1]
    d = base_dir / cfg.dir_name
    d.mkdir(parents=True, exist_ok=True)
    return d / cfg.file_name


def append_journal_event(
    event_type: str,
    payload: Dict[str, Any],
    *,
    actor: str = "system",
    base_dir: Optional[Path] = None,
    cfg: JournalConfig = JournalConfig(),
) -> bool:
    """
    Append one JSONL event.

    Event envelope:
    - schema_version
    - ts
    - event_type
    - actor
    - payload
    """
    try:
        p = _journal_path(base_dir=base_dir, cfg=cfg)
        evt = {
            "schema_version": cfg.schema_version,
            "ts": _now_iso_cn(),
            "event_type": str(event_type),
            "actor": str(actor),
            "payload": payload or {},
        }
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception:
        return False

