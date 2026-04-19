"""选股熔断标志文件：`data/screening/emergency_pause.json`。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def screening_data_dir() -> Path:
    d = _root() / "data" / "screening"
    d.mkdir(parents=True, exist_ok=True)
    return d


def emergency_pause_path() -> Path:
    return screening_data_dir() / "emergency_pause.json"


def is_emergency_pause_active() -> bool:
    p = emergency_pause_path()
    if not p.is_file():
        return False
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not j.get("active"):
        return False
    until = j.get("until")
    if until:
        try:
            # ISO date or datetime
            if "T" in str(until):
                u = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > u.astimezone(timezone.utc):
                    return False
            else:
                uday = datetime.strptime(str(until)[:10], "%Y-%m-%d").date()
                if datetime.now(timezone.utc).date() > uday:
                    return False
        except Exception:
            pass
    return True


def write_emergency_pause(active: bool, reason: str = "", until: Optional[str] = None) -> Path:
    p = emergency_pause_path()
    payload: Dict[str, Any] = {
        "active": bool(active),
        "reason": reason,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if until:
        payload["until"] = until
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def read_weekly_regime_pause() -> bool:
    """config/weekly_calibration.json 中 regime == pause 视为定调熔断。"""
    p = _root() / "config" / "weekly_calibration.json"
    if not p.is_file():
        return False
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    return str(j.get("regime") or "").strip().lower() == "pause"
