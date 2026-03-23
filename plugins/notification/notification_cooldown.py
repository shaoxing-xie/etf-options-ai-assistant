"""
Notification cooldown / debouncing helper.

Purpose:
- Prevent notification flooding for repeated events within a short window.
- Persist state locally under ~/.openclaw/workspace/ to survive process restarts.

This module is intentionally lightweight and does not perform sending; it only
decides whether a notification should be sent and records successful sends.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict


STATE_PATH = os.path.expanduser("~/.openclaw/workspace/notification_cooldown_state.json")


@dataclass
class CooldownDecision:
    allowed: bool
    reason: str


def _load_state() -> Dict[str, Any]:
    try:
        if not os.path.exists(STATE_PATH):
            return {"lastSends": {}}
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"lastSends": {}}
        data.setdefault("lastSends", {})
        return data
    except Exception:
        return {"lastSends": {}}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def should_send(*, key: str, cooldown_minutes: int) -> CooldownDecision:
    key = (key or "").strip()
    if not key:
        return CooldownDecision(allowed=True, reason="no_key")

    cooldown_minutes = max(0, int(cooldown_minutes))
    if cooldown_minutes <= 0:
        return CooldownDecision(allowed=True, reason="cooldown_disabled")

    state = _load_state()
    last_sends = state.get("lastSends", {}) or {}
    last_ts = last_sends.get(key)
    if isinstance(last_ts, str):
        try:
            last_dt = datetime.fromisoformat(last_ts)
            if datetime.now() - last_dt < timedelta(minutes=cooldown_minutes):
                return CooldownDecision(allowed=False, reason=f"dedup_within_{cooldown_minutes}min")
        except Exception:
            pass

    return CooldownDecision(allowed=True, reason="ok")


def record_send(*, key: str) -> None:
    key = (key or "").strip()
    if not key:
        return
    state = _load_state()
    last_sends = state.get("lastSends", {}) or {}
    last_sends[key] = datetime.now().isoformat(timespec="seconds")
    state["lastSends"] = last_sends
    _save_state(state)

