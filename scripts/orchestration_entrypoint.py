#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.orchestration.dependency_engine import DependencyEngine
from src.orchestration.task_state_manager import TaskStateManager


def _load_context(*, trade_date: str) -> dict:
    """与 nightly / intraday 脚本侧 `_load_orchestration_context` 对齐，供 DependencyEngine 评估。"""
    context: dict = {"is_trading_day": True, "position_ceiling": 1.0}
    cal = ROOT / "config" / "weekly_calibration.json"
    if cal.is_file():
        try:
            obj = json.loads(cal.read_text(encoding="utf-8"))
        except Exception:
            obj = {}
        if isinstance(obj, dict) and obj.get("position_ceiling") is not None:
            try:
                context["position_ceiling"] = float(obj.get("position_ceiling", 1.0))
            except (TypeError, ValueError):
                context["position_ceiling"] = 1.0
    def _read_sentiment_json(path: Path) -> dict:
        if not path.is_file():
            return {}
        try:
            o = json.loads(path.read_text(encoding="utf-8"))
            return o if isinstance(o, dict) else {}
        except Exception:
            return {}

    day_snap = _read_sentiment_json(ROOT / "data" / "sentiment_check" / f"{trade_date}.json")
    latest_snap: dict = {}
    sentiment_files = sorted((ROOT / "data" / "sentiment_check").glob("*.json"))
    if sentiment_files:
        latest_snap = _read_sentiment_json(sentiment_files[-1])
    snap = day_snap if isinstance(day_snap.get("sentiment_dispersion"), (int, float)) else latest_snap
    if not isinstance(snap.get("sentiment_dispersion"), (int, float)) and latest_snap:
        snap = latest_snap
    if isinstance(snap, dict):
        if snap.get("sentiment_stage") is not None:
            context["sentiment_stage"] = snap.get("sentiment_stage")
        if isinstance(snap.get("sentiment_dispersion"), (int, float)):
            context["sentiment_dispersion"] = snap["sentiment_dispersion"]
    pause = ROOT / "data" / "screening" / "emergency_pause.json"
    if pause.is_file():
        try:
            obj = json.loads(pause.read_text(encoding="utf-8"))
        except Exception:
            obj = {}
        if isinstance(obj, dict):
            context["emergency_pause_active"] = bool(obj.get("active"))
    return context


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--trade-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--trigger-source", default="cron")
    ap.add_argument("--trigger-window", default="daily")
    ap.add_argument(
        "--session-type",
        default="",
        help="Optional session type suffix for idempotency (e.g. 'manual'). "
        "If omitted, reads ORCH_SESSION_TYPE env var.",
    )
    ap.add_argument("--depends-on", default="")
    ap.add_argument("--conditions", default="")
    ap.add_argument("--timeout-seconds", type=int, default=60)
    ap.add_argument("--command", required=True, help="Shell command to execute after orchestration checks.")
    args = ap.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    depends_on = [x.strip() for x in args.depends_on.split(",") if x.strip()]
    conditions = [x.strip() for x in args.conditions.split(",") if x.strip()]
    session_type = (args.session_type or "").strip() or str((os.environ.get("ORCH_SESSION_TYPE") or "")).strip()
    st_l = session_type.lower()
    is_manual_session = st_l == "manual" or st_l.startswith("manual:")
    mgr = TaskStateManager(
        root=ROOT,
        task_id=args.task_id,
        trade_date=args.trade_date,
        run_id=run_id,
        trigger_source=args.trigger_source,
        trigger_window=args.trigger_window,
        session_type=session_type,
    )
    ok, reason = mgr.claim_execution(depends_on=depends_on)
    if not ok:
        print(json.dumps({"success": True, "message": reason}, ensure_ascii=False))
        return 0
    if not is_manual_session:
        dep_wait = mgr.wait_for_dependencies(depends_on, timeout_seconds=args.timeout_seconds, poll_seconds=1.0)
        if not dep_wait.satisfied:
            mgr.finish(to_state="skipped", reason=dep_wait.reason, depends_on=depends_on, condition_met=False)
            print(
                json.dumps(
                    {"success": False, "message": dep_wait.reason, "missing": dep_wait.missing},
                    ensure_ascii=False,
                )
            )
            return 2
        eval_result = DependencyEngine().evaluate(_load_context(trade_date=args.trade_date), conditions)
        if not eval_result.passed:
            reason = f"condition_not_met:{','.join(eval_result.failed_conditions)}"
            mgr.finish(to_state="skipped", reason=reason, depends_on=depends_on, condition_met=False)
            print(json.dumps({"success": False, "message": reason, "details": eval_result.details}, ensure_ascii=False))
            return 3
    try:
        proc = subprocess.run(args.command, shell=True, cwd=str(ROOT))
    except BaseException as exc:
        # 避免 claim 后子 shell 未启动/被中断时 state 永久卡在 running（SIGINT、资源错误等）
        try:
            mgr.finish(
                to_state="failed",
                reason=f"orchestrator_exception:{type(exc).__name__}",
                depends_on=depends_on,
                condition_met=False,
            )
        except Exception:
            pass
        raise
    if proc.returncode == 0:
        mgr.finish(to_state="succeeded", reason="completed", depends_on=depends_on, condition_met=True)
        return 0
    mgr.finish(to_state="failed", reason=f"command_failed:{proc.returncode}", depends_on=depends_on, condition_met=True)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
