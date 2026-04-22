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

from src.orchestration.task_state_manager import TaskStateManager


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except Exception:
        return None


def main() -> int:
    # trade_date 以 UTC 日期落盘（与既有语义快照口径一致）
    trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    depends_on: list[str] = []

    mgr = TaskStateManager(
        root=ROOT,
        task_id="pre-market-sentiment-check",
        trade_date=trade_date,
        run_id=run_id,
        trigger_source=str(os.environ.get("ORCH_TRIGGER_SOURCE") or "cron").strip().lower(),
        trigger_window="daily",
    )
    claimed, reason = mgr.claim_execution(depends_on=depends_on)
    if not claimed:
        print(json.dumps({"success": True, "message": reason, "trade_date": trade_date}, ensure_ascii=False))
        return 0

    quality_status = "ok"
    degraded = False
    lineage: list[str] = []
    try:
        ts = _run_tool("tool_check_trading_status", {})  # type: ignore[arg-type]
        lineage.append("tool_check_trading_status")
        limit_up = _run_tool("tool_fetch_limit_up_stocks", {})
        fund_flow = _run_tool("tool_fetch_a_share_fund_flow", {"query_kind": "market_history", "max_days": 5})
        north = _run_tool("tool_fetch_northbound_flow", {"lookback_days": 5})
        sector = _run_tool("tool_fetch_sector_data", {"sector_type": "industry", "period": "today"})
        for obj in (limit_up, fund_flow, north, sector):
            if not bool(obj.get("success")):
                degraded = True
                quality_status = "degraded"
    except Exception as exc:
        degraded = True
        quality_status = "error"
        mgr.finish(to_state="failed", reason=f"tool_failed:{type(exc).__name__}", depends_on=depends_on, condition_met=True)
        print(json.dumps({"success": False, "message": str(exc)}, ensure_ascii=False))
        return 1

    # 生成最小侧车（满足 docs/sentiment/api_contract.md 的必需键）
    overall_score = None
    sentiment_stage = "中性"
    sentiment_dispersion = None
    try:
        # 规则：不做复杂口径推断，只给稳定可追溯默认值；后续可由 workflow 细化
        overall_score = 60.0 if not degraded else 50.0
        sentiment_dispersion = 0.5 if not degraded else 0.7
    except Exception:
        pass

    payload = {
        "overall_score": overall_score,
        "sentiment_stage": sentiment_stage,
        "factor_attribution": {
            "limit_up": {"success": bool(limit_up.get("success")), "count": len((limit_up.get("data") or {}).get("records") or []) if isinstance(limit_up.get("data"), dict) else None},
            "market_history": {"success": bool(fund_flow.get("success"))},
            "northbound": {"success": bool(north.get("success")), "data_date": (north.get("data") or {}).get("date") if isinstance(north.get("data"), dict) else None},
            "sector": {"success": bool(sector.get("success"))},
        },
        "sentiment_dispersion": sentiment_dispersion,
        "data_completeness_ratio": _safe_float(sum(1 for x in (limit_up, fund_flow, north, sector) if bool(x.get("success"))) / 4.0),
        "action_bias": "neutral",
        "risk_counterevidence": [],
        "confidence_band": "medium" if not degraded else "low",
        "degraded": bool(degraded),
        "sentiment_meta": {
            "sentinel_version": "v1",
            "weight_profile": "default",
            "generated_at": _utc_now_iso(),
        },
        "cache_ttl_policy": {"opening_first_hour": 300, "mid_session": 900, "closing_hour": 600},
    }

    # sidecar 落盘：最新快照 + 历史审计
    sidecar_dir = ROOT / "data" / "sentiment_check"
    hist_dir = sidecar_dir / "history"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    hist_dir.mkdir(parents=True, exist_ok=True)
    latest_path = sidecar_dir / f"{trade_date}.json"
    hist_path = hist_dir / f"{trade_date}__{datetime.now(timezone.utc).strftime('%H%M%S')}.json"
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    hist_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 生成语义快照（L4）并通知
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "persist_pre_market_semantic_snapshot.py")],
            cwd=str(ROOT),
            check=True,
            text=True,
            capture_output=True,
            env=dict(os.environ),
        )
        _run_tool(
            "tool_send_feishu_message",
            {
                "title": "09:10 情绪前置检查",
                "message": f"{trade_date} overall_score={overall_score} stage={sentiment_stage} degraded={degraded}",
                "cooldown_minutes": 0,
            },
        )
    except Exception as exc:
        mgr.finish(to_state="failed", reason=f"persist_or_notify_failed:{type(exc).__name__}", depends_on=depends_on, condition_met=True)
        print(json.dumps({"success": False, "message": str(exc)}, ensure_ascii=False))
        return 1

    mgr.finish(to_state="succeeded", reason=f"completed:{quality_status}", depends_on=depends_on, condition_met=True)
    print(json.dumps({"success": True, "trade_date": trade_date, "degraded": degraded}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
