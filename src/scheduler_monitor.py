"""
Scheduler 执行历史监控（用于“定时任务查询”）

记录 APScheduler 任务最近执行情况：执行时间、成功/失败、异常摘要等。
仅使用内存 ring buffer，避免写盘。
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Deque, Dict, Optional, List

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


@dataclass
class JobRunRecord:
    job_id: str
    scheduled_run_time: Optional[str] = None
    finished_at: Optional[str] = None
    status: str = "unknown"  # success/error/missed
    error: Optional[str] = None


_history: Dict[str, Deque[JobRunRecord]] = defaultdict(lambda: deque(maxlen=20))


def _to_iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    try:
        return str(dt)
    except Exception:
        return None


def record_event(event: Any) -> None:
    """
    记录 APScheduler 事件（EVENT_JOB_EXECUTED / EVENT_JOB_ERROR / EVENT_JOB_MISSED）。
    """
    try:
        job_id = getattr(event, "job_id", "unknown")
        scheduled_run_time = _to_iso(getattr(event, "scheduled_run_time", None))

        status = "success"
        err = None
        if getattr(event, "exception", None) is not None:
            status = "error"
            err = str(getattr(event, "exception"))
        # missed 事件通常没有 exception，但有 code；这里简单识别
        if getattr(event, "code", None) is not None and "MISSED" in str(getattr(event, "code")):
            status = "missed"

        rec = JobRunRecord(
            job_id=job_id,
            scheduled_run_time=scheduled_run_time,
            finished_at=datetime.now().isoformat(),
            status=status,
            error=err,
        )
        _history[job_id].appendleft(rec)
    except Exception as e:
        logger.debug(f"记录scheduler事件失败（不影响主流程）: {e}")


def get_recent_history(job_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    获取最近执行历史。

    Returns:
        { job_id: [record,...] }
    """
    if job_id:
        return {job_id: [asdict(r) for r in list(_history.get(job_id, []))]}
    return {jid: [asdict(r) for r in list(recs)] for jid, recs in _history.items()}

