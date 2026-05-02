from __future__ import annotations

from typing import Any, Dict, Optional


def tool_run_data_cache_job(
    job: str,
    *,
    throttle_stock: bool = False,
    notify: Optional[bool] = None,
    feishu_title: Optional[str] = None,
) -> Dict[str, Any]:
    """
    OpenClaw tool: run a single data_cache collection phase.

    This is the canonical import path used by `tool_runner`:
    `data_collection.run_data_cache_job`.
    """
    from src.data_cache_collection_core import (
        feishu_notify_title_and_body_for_cache_job,
        run_data_cache_collection,
        summary_success,
    )

    job_name = str(job or "").strip()
    if not job_name:
        return {"success": False, "message": "job is required", "job": job}

    if notify is None:
        notify_effective = job_name in ("morning_daily", "close_minute")
    else:
        notify_effective = bool(notify)

    summary = run_data_cache_collection(
        job_name, throttle_stock=bool(throttle_stock)
    )
    ok = summary_success(summary)

    out: Dict[str, Any] = {
        "success": bool(ok),
        "collection_success": bool(ok),
        "job": job_name,
        "notify": bool(notify_effective),
        "notify_result": None,
        "summary": summary,
    }

    if notify_effective:
        from plugins.notification.send_feishu_message import tool_send_feishu_message

        title, body = feishu_notify_title_and_body_for_cache_job(
            job_name,
            summary,
            collection_ok=bool(ok),
            title_override=feishu_title,
        )
        sent = tool_send_feishu_message(message=body, title=title, cooldown_minutes=0)
        out["notification"] = sent
        out["notify_result"] = sent
        out["success"] = bool(ok) and bool(sent.get("success"))

    return out

