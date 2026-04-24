#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_layer import MetaEnvelope, write_contract_json
from src.orchestration.task_state_manager import TaskStateManager


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def main() -> int:
    trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    depends_on: list[str] = []
    session_type = str(os.environ.get("ORCH_SESSION_TYPE") or "").strip().lower()
    is_manual_session = session_type == "manual"

    mgr = TaskStateManager(
        root=ROOT,
        task_id="strategy-calibration",
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
        wait = mgr.wait_for_dependencies(depends_on, timeout_seconds=90, poll_seconds=1.0)
        if not wait.satisfied:
            mgr.finish(to_state="skipped", reason=wait.reason, depends_on=depends_on, condition_met=False)
            print(json.dumps({"success": True, "message": wait.reason, "missing": wait.missing}, ensure_ascii=False))
            return 0

    snap = _read_json(ROOT / "data" / "sentiment_check" / f"{trade_date}.json")
    stage = str(snap.get("sentiment_stage") or "中性")
    dispersion = snap.get("sentiment_dispersion")

    # 最小定调：以阶段为主，不做重策略推断（保证稳定可回放）
    regime = "oscillation"
    if any(x in stage for x in ("偏多", "高潮")):
        regime = "trend_up"
    if any(x in stage for x in ("冰点", "退潮", "极端")):
        regime = "risk_off"

    position_ceiling = 1.0
    if regime == "risk_off":
        position_ceiling = 0.0
    elif regime == "trend_up":
        position_ceiling = 1.0
    else:
        position_ceiling = 0.6

    out_cfg = {
        "version": "1.0.0",
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "regime": regime,
        "position_ceiling": position_ceiling,
        "notes": f"auto_from_sentiment_stage={stage} dispersion={dispersion}",
    }
    (ROOT / "config").mkdir(parents=True, exist_ok=True)
    (ROOT / "config" / "weekly_calibration.json").write_text(json.dumps(out_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # L3 决策落盘（与 migrate_task_outputs_to_new_layer.py 预期路径对齐）
    write_contract_json(
        ROOT / "data" / "decisions" / "signals" / f"strategy_calibration_{trade_date}.json",
        payload=out_cfg,
        meta=MetaEnvelope(
            schema_name="orchestration_state_v1",
            schema_version="1.0.0",
            task_id="strategy-calibration",
            run_id=run_id,
            data_layer="L3",
            trade_date=trade_date,
            quality_status="ok",
            lineage_refs=[f"data/sentiment_check/{trade_date}.json"],
            source_tools=["strategy_calibration_and_persist.py"],
        ),
    )

    # 通知（不强制失败）
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "tool_runner.py"), "tool_send_feishu_message", json.dumps({"title": "周度策略定调", "message": f"{trade_date} regime={regime} position_ceiling={position_ceiling}", "cooldown_minutes": 0}, ensure_ascii=False)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=True,
        )
    except Exception:
        pass

    mgr.finish(to_state="succeeded", reason="completed", depends_on=depends_on, condition_met=True)
    print(json.dumps({"success": True, "trade_date": trade_date, "regime": regime}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
