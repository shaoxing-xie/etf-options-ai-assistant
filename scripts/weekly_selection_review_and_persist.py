#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.orchestration.task_state_manager import TaskStateManager


def main() -> int:
    trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    depends_on: list[str] = []
    session_type = str(os.environ.get("ORCH_SESSION_TYPE") or "").strip().lower()
    is_manual_session = session_type == "manual"

    mgr = TaskStateManager(
        root=ROOT,
        task_id="weekly-selection-review",
        trade_date=trade_date,
        run_id=run_id,
        trigger_source=str(os.environ.get("ORCH_TRIGGER_SOURCE") or "cron").strip().lower(),
        trigger_window="weekly",
    )
    claimed, reason = mgr.claim_execution(depends_on=depends_on)
    if not claimed:
        print(json.dumps({"success": True, "message": reason, "trade_date": trade_date}, ensure_ascii=False))
        return 0

    if not is_manual_session:
        wait = mgr.wait_for_dependencies(depends_on, timeout_seconds=120, poll_seconds=1.0)
        if not wait.satisfied:
            mgr.finish(to_state="skipped", reason=wait.reason, depends_on=depends_on, condition_met=False)
            print(json.dumps({"success": True, "message": wait.reason, "missing": wait.missing}, ensure_ascii=False))
            return 0

    # 最小复盘产物：weekly_review.json（供闭环脚本消费），不强行做复杂回测口径
    out_dir = ROOT / "data" / "screening"
    out_dir.mkdir(parents=True, exist_ok=True)
    weekly = {
        "as_of": trade_date,
        "period_label": "week",
        "metrics": {},
        "suggestions": [],
    }
    (out_dir / "weekly_review.json").write_text(json.dumps(weekly, ensure_ascii=False, indent=2), encoding="utf-8")

    # 反馈事件化（闭环）：写入 orchestration events
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "persist_weekly_review_feedback.py")],
            cwd=str(ROOT),
            check=True,
            text=True,
            capture_output=True,
        )
    except Exception as exc:
        mgr.finish(to_state="failed", reason=f"feedback_persist_failed:{type(exc).__name__}", depends_on=depends_on, condition_met=True)
        print(json.dumps({"success": False, "message": str(exc)}, ensure_ascii=False))
        return 1

    mgr.finish(to_state="succeeded", reason="completed", depends_on=depends_on, condition_met=True)
    print(json.dumps({"success": True, "trade_date": trade_date}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
