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


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, env=dict(os.environ))
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, out.strip()


def main() -> int:
    # 使用未来日期，避免与真实生产 trade_date 冲突
    trade_date = "2099-01-01"
    venv_py = str(ROOT / ".venv" / "bin" / "python")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1) already_executed：同 task+trade_date+window 二次触发直接跳过
    mgr1 = TaskStateManager(
        root=ROOT,
        task_id="nightly-stock-screening",
        trade_date=trade_date,
        run_id="r1",
        trigger_source="cron",
        trigger_window="daily",
    )
    ok1, _ = mgr1.claim_execution(depends_on=[])
    mgr1.finish(to_state="succeeded", reason="completed", depends_on=[], condition_met=True)
    mgr2 = TaskStateManager(
        root=ROOT,
        task_id="nightly-stock-screening",
        trade_date=trade_date,
        run_id="r2",
        trigger_source="dependency",
        trigger_window="daily",
    )
    ok2, reason2 = mgr2.claim_execution(depends_on=[])

    # 2) duplicate_trigger：并发窗口内 second runner 看到 running -> duplicate_trigger
    mgr3 = TaskStateManager(
        root=ROOT,
        task_id="intraday-tail-screening",
        trade_date=trade_date,
        run_id="r3",
        trigger_source="cron",
        trigger_window="intraday-30m",
    )
    ok3, _ = mgr3.claim_execution(depends_on=[])
    mgr4 = TaskStateManager(
        root=ROOT,
        task_id="intraday-tail-screening",
        trade_date=trade_date,
        run_id="r4",
        trigger_source="dependency",
        trigger_window="intraday-30m",
    )
    ok4, reason4 = mgr4.claim_execution(depends_on=[])
    mgr3.finish(to_state="succeeded", reason="completed", depends_on=[], condition_met=True)

    # 3) 真实链路冒烟：跑 entrypoint (command=true) 验证入口可执行
    code, out = _run(
        [
            venv_py,
            str(ROOT / "scripts" / "orchestration_entrypoint.py"),
            "--task-id",
            "pre-market-sentiment-check",
            "--trade-date",
            trade_date,
            "--trigger-source",
            "cron",
            "--trigger-window",
            "daily",
            "--depends-on",
            "",
            "--conditions",
            "is_trading_day",
            "--timeout-seconds",
            "3",
            "--command",
            "true",
        ]
    )

    evidence = {
        "generated_at": now,
        "trade_date": trade_date,
        "checks": {
            "already_executed": {"first_claim_ok": ok1, "second_claim_ok": ok2, "second_reason": reason2},
            "duplicate_trigger": {"first_claim_ok": ok3, "second_claim_ok": ok4, "second_reason": reason4},
            "entrypoint_smoke": {"exit_code": code, "output_tail": out[-400:]},
        },
        "result": "ok" if (ok1 and (not ok2) and ok3 and (not ok4) and code == 0) else "degraded",
    }
    out_dir = ROOT / "data" / "meta" / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"orchestration_e2e_smoke_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "evidence": str(path), "result": evidence["result"]}, ensure_ascii=False))
    return 0 if evidence["result"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
