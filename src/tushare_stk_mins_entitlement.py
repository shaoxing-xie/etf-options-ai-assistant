"""Tushare stk_mins (table-2 minute) entitlement — keep in sync with plugins.connectors.tushare."""

from __future__ import annotations

import os
from typing import Any, Dict


def get_permission_profile(config: Dict[str, Any] | None) -> str:
    if not isinstance(config, dict):
        return str(os.environ.get("TUSHARE_PERMISSION_PROFILE") or "2000")
    t = config.get("tushare")
    if isinstance(t, dict) and t.get("permission_profile"):
        return str(t.get("permission_profile"))
    return "2000"


def _env_truthy(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def is_stk_mins_entitled(config: Dict[str, Any] | None) -> bool:
    if _env_truthy("TUSHARE_FORCE_STK_MINS") or _env_truthy("TUSHARE_STK_MINS_ENTITLED"):
        return True
    if not isinstance(config, dict):
        return get_permission_profile(None).strip().lower() == "minute_table2"
    t = config.get("tushare")
    if isinstance(t, dict):
        if t.get("minute_table2") is True:
            return True
        ent = t.get("minute_entitlement")
        if ent is True:
            return True
        if isinstance(ent, str) and ent.strip().lower() == "minute_table2":
            return True
    return get_permission_profile(config).strip().lower() == "minute_table2"
