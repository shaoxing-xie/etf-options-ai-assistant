"""Optional debug fields for plugin catalog merge / engine routing (observability only)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict


def debug_plugin_catalog_enabled() -> bool:
    v = os.environ.get("OPTION_TRADING_ASSISTANT_DEBUG_PLUGIN_CATALOG", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def extract_global_index_spot_catalog_debug(payload: Any) -> Dict[str, Any]:
    """Slice `tool_fetch_global_index_spot` / global_spot-shaped payloads for logs and `_debug` blocks."""
    if not isinstance(payload, dict):
        return {}
    sr = payload.get("source_route")
    out: Dict[str, Any] = {}
    if isinstance(sr, dict):
        for key in ("catalog_merge", "active_priority", "metric", "route"):
            if key in sr:
                out[key] = sr[key]
    att = payload.get("attempts")
    if isinstance(att, list):
        out["attempts_count"] = len(att)
    if payload.get("elapsed_ms") is not None:
        out["elapsed_ms"] = payload.get("elapsed_ms")
    return out


def compact_json_for_diag(obj: Any, max_len: int = 400) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        s = str(obj)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s
