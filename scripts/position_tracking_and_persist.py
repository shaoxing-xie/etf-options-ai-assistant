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


def _run_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tool_runner.py"), name, json.dumps(args, ensure_ascii=False)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        env=dict(os.environ),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or f"tool failed: {name}")
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def main() -> int:
    trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    depends_on: list[str] = []
    session_type = str(os.environ.get("ORCH_SESSION_TYPE") or "").strip().lower()
    is_manual_session = session_type == "manual"

    mgr = TaskStateManager(
        root=ROOT,
        task_id="position-tracking",
        trade_date=trade_date,
        run_id=run_id,
        trigger_source=str(os.environ.get("ORCH_TRIGGER_SOURCE") or "cron").strip().lower(),
        trigger_window="intraday-30m",
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

    wl = _read_json(ROOT / "data" / "watchlist" / "default.json")
    symbols = wl.get("symbols") if isinstance(wl.get("symbols"), list) else []
    codes = [str(x).strip() for x in symbols if str(x).strip()]
    codes = [c for c in codes if len(c) == 6 and c.isdigit()][:50]
    snapshot: dict[str, Any] = {"symbols": codes, "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    # 轻量抓取实时（不影响落盘结构，不强依赖）
    rt: dict[str, Any] = {}
    if codes:
        try:
            res = _run_tool("tool_fetch_stock_realtime", {"stock_code": ",".join(codes), "mode": "production"})
            rt = res.get("data") if isinstance(res.get("data"), dict) else {"raw": res.get("data")}
        except Exception:
            rt = {}
    snapshot["realtime"] = rt

    out = ROOT / "data" / "decisions" / "watchlist" / "history" / f"{trade_date}.json"
    write_contract_json(
        out,
        payload=snapshot,
        meta=MetaEnvelope(
            schema_name="watchlist_state_v1",
            schema_version="1.0.0",
            task_id="position-tracking",
            run_id=run_id,
            data_layer="L3",
            trade_date=trade_date,
            quality_status="ok" if rt else "degraded",
            lineage_refs=[str(ROOT / "data" / "watchlist" / "default.json")],
            source_tools=["position_tracking_and_persist.py"],
        ),
    )
    mgr.finish(to_state="succeeded", reason="completed", depends_on=depends_on, condition_met=True)
    print(json.dumps({"success": True, "trade_date": trade_date, "symbol_count": len(codes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
