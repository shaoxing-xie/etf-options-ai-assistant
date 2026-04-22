from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FEATURE_FLAGS_PATH = ROOT / "config" / "feature_flags.json"


def _load() -> dict[str, Any]:
    if not FEATURE_FLAGS_PATH.is_file():
        return {}
    try:
        obj = json.loads(FEATURE_FLAGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def is_enabled(key: str, default: bool = False) -> bool:
    return bool(_load().get(key, default))


def legacy_write_allowed(task_id: str) -> bool:
    flags = _load()
    if not bool(flags.get("legacy_write_enabled", True)):
        return False
    disabled = flags.get("legacy_write_disabled_tasks") or []
    return task_id not in disabled
