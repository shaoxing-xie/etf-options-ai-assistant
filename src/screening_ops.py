"""
夜盘选股收尾：落盘 JSON、质量门禁、观察池合并、熔断尊重。
供 tool_runner 与 scripts/nightly_screening_and_persist.py 共用。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.screening_gate_files import screening_data_dir
from src.screening_quality_gate import screening_allow_watchlist, screening_should_skip_due_to_pause
from src.screening_utils import validate_screening_response
from src.watchlist_storage import merge_screening_picks


def _today_shanghai() -> str:
    try:
        import pytz

        tz = pytz.timezone("Asia/Shanghai")
        return datetime.now(tz).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def tool_finalize_screening_nightly(
    screening_result: Optional[Dict[str, Any]] = None,
    run_date: str = "",
    attempt_watchlist: bool = True,
) -> Dict[str, Any]:
    """
    将 `tool_screen_equity_factors` 完整返回写入 `data/screening/{date}.json`；
    若未熔断且通过门禁则合并观察池。

    screening_result: 工具返回的 dict（须含 success、data、quality_score 等）。
    """
    payload = screening_result if isinstance(screening_result, dict) else {}
    ok_schema, issues = validate_screening_response(payload)
    date_key = (run_date or "").strip() or _today_shanghai()
    out_dir = screening_data_dir()
    out_path = out_dir / f"{date_key}.json"

    pause, pause_reason = screening_should_skip_due_to_pause()
    allow_wl, gate_reasons = screening_allow_watchlist(payload)
    merged_path: Optional[str] = None
    watchlist_skipped: List[str] = []
    if pause:
        watchlist_skipped.append(pause_reason)
    elif not allow_wl:
        watchlist_skipped.extend(gate_reasons)
    elif attempt_watchlist and payload.get("success"):
        try:
            p = merge_screening_picks(payload)
            merged_path = str(p)
        except Exception as e:  # noqa: BLE001
            watchlist_skipped.append(f"merge_failed:{e}")

    artifact = {
        "run_date": date_key,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_ok": ok_schema,
        "schema_issues": issues,
        "pause_active": pause,
        "pause_reason": pause_reason if pause else None,
        "watchlist_allowed": allow_wl and not pause,
        "gate_reasons": gate_reasons,
        "watchlist_skipped": watchlist_skipped,
        "merged_watchlist_path": merged_path,
        "screening": payload,
    }
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    success = bool(payload.get("success")) and ok_schema
    return {
        "success": success,
        "message": "ok" if success else "screening or schema failed",
        "artifact_path": str(out_path),
        "watchlist_merged": merged_path is not None,
        "watchlist_skipped": watchlist_skipped,
        "pause_active": pause,
    }


def tool_set_screening_emergency_pause(
    active: bool = True,
    reason: str = "",
    until: str = "",
) -> Dict[str, Any]:
    """写入 `data/screening/emergency_pause.json`。"""
    from src.screening_gate_files import write_emergency_pause

    p = write_emergency_pause(active=active, reason=reason or "", until=until or None)
    return {"success": True, "path": str(p), "active": active}
