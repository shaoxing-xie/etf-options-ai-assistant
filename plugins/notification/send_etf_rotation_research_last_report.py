from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from .send_analysis_report import tool_send_analysis_report


def _today_key(tz_name: str = "Asia/Shanghai") -> str:
    tz = ZoneInfo(tz_name)
    return datetime.now(tz).strftime("%Y-%m-%d")


def _memory_dir() -> Path:
    p = Path(os.environ.get("OPENCLAW_MEMORY_DIR", str(Path.home() / ".openclaw" / "memory")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def tool_send_etf_rotation_research_last_report(
    *,
    mode: str = "prod",
    max_age_days: int = 3,
    idempotency_scope: str = "daily",
) -> Dict[str, Any]:
    """
    发送工具：只用一次“发送”，但 report_data 从 `tool_etf_rotation_research` 落盘读取。

    解决点：
    - agent 不稳定时不必把大段 report_data 作为参数转交给发送工具
    - VERIFY_SEND 仍可通过 toolResult evidence 校验（发送工具是 tool_send_*）
    """
    date_key = _today_key()
    p = _memory_dir() / f"etf_rotation_last_report_{date_key}.json"
    chosen_path = p
    if not chosen_path.exists():
        # 兜底：当天报告缺失时，允许回退最近 N 天缓存（默认3天）。
        mem = _memory_dir()
        candidates = sorted(mem.glob("etf_rotation_last_report_*.json"), reverse=True)
        threshold = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=max(0, int(max_age_days)))
        picked: Optional[Path] = None
        for c in candidates:
            try:
                ds = c.stem.rsplit("_", 1)[-1]
                d = datetime.strptime(ds, "%Y-%m-%d").date()
            except Exception:
                continue
            if d >= threshold:
                picked = c
                break
        if picked is None:
            return {"success": False, "message": f"missing last rotation report: {p}", "data": {"path": str(p)}}
        chosen_path = picked

    try:
        obj = _safe_read_json(chosen_path)
    except Exception as e:  # pylint: disable=broad-except
        return {"success": False, "message": f"failed read last rotation report: {e}", "data": {"path": str(chosen_path)}}

    report_data = obj.get("report_data")
    if not isinstance(report_data, dict) or not report_data.get("report_type"):
        return {"success": False, "message": "invalid cached report_data", "data": {"cached": obj}}

    send_out = tool_send_analysis_report(report_data=report_data, mode=mode, idempotency_scope=idempotency_scope)
    return {
        "success": bool(isinstance(send_out, dict) and send_out.get("success")),
        "data": {"send": send_out, "cached_report_path": str(chosen_path)},
        "message": send_out.get("message") if isinstance(send_out, dict) else "unknown",
    }

