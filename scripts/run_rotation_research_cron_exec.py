#!/home/xie/etf-options-ai-assistant/.venv/bin/python
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ENV_PATH = "/home/xie/.openclaw/.env"
ROOT = Path("/home/xie/etf-options-ai-assistant")
MEMORY_DIR = Path("/home/xie/.openclaw/memory")


def _load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k:
                os.environ[k] = v


def _today_shanghai() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _backfill_semantic_from_cached_report(trade_date: str) -> bool:
    cached_path = MEMORY_DIR / f"etf_rotation_last_report_{trade_date}.json"
    if not cached_path.exists():
        return False
    try:
        cached = json.loads(cached_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    report_data = cached.get("report_data") if isinstance(cached, dict) else {}
    raw = report_data.get("raw") if isinstance(report_data, dict) else {}
    ranked = raw.get("ranked") if isinstance(raw, dict) and isinstance(raw.get("ranked"), list) else []
    top = ranked[:5]

    heatmap_counts: dict[str, int] = {}
    for item in ranked:
        pt = str(item.get("pool_type") or "unknown")
        heatmap_counts[pt] = heatmap_counts.get(pt, 0) + 1
    heatmap = [{"sector_name": k, "count": v} for k, v in sorted(heatmap_counts.items(), key=lambda kv: kv[0])]

    latest_payload = {
        "_meta": {
            "schema_name": "etf_rotation_latest_semantic_v1",
            "schema_version": "1.1.0",
            "task_id": "etf-rotation-research",
            "run_id": f"autobackfill_{datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%dT%H%M%S')}",
            "data_layer": "L4",
            "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "trade_date": trade_date,
            "quality_status": "degraded",
            "lineage_refs": [str(cached_path)],
        },
        "data": {
            "trade_date": trade_date,
            "top5": top,
            "top10": ranked[:10],
            "heatmap": heatmap,
            "environment": {"stage": "偏多", "dispersion": 0.05, "gate_multiplier": 1.0},
            "data_quality": {
                "quality_status": "degraded",
                "degraded_reasons": ["backfilled_from_cached_rotation_report"],
                "warnings": [],
                "errors": [],
                "structured_warnings": [],
            },
            "links": {"cached_report_path": str(cached_path)},
            "ranked_by_pool": {"industry": [], "concept": []},
            "three_factor_context": {"enabled": True, "by_symbol": {}},
            "unified_next_day": [],
            "legacy_views": {
                "three_factor_top5": top,
                "three_factor_top10": ranked[:10],
                "rps_recommendations": [],
            },
            "sector_environment_effective": {},
        },
    }
    heatmap_payload = {
        "_meta": {
            "schema_name": "semantic_rotation_heatmap_v1",
            "schema_version": "1.0.0",
            "task_id": "etf-rotation-research",
            "run_id": latest_payload["_meta"]["run_id"],
            "data_layer": "L4",
            "generated_at": latest_payload["_meta"]["generated_at"],
            "trade_date": trade_date,
            "quality_status": "degraded",
            "lineage_refs": [str(cached_path)],
        },
        "data": {
            "trade_date": trade_date,
            "heatmap": heatmap,
            "top5": top,
            "environment": {"stage": "偏多", "dispersion": 0.05, "gate_multiplier": 1.0},
            "explanations": {"degraded_reasons": ["backfilled_from_cached_rotation_report"], "warnings": []},
        },
    }

    _write_json(ROOT / "data" / "semantic" / "rotation_latest" / f"{trade_date}.json", latest_payload)
    _write_json(ROOT / "data" / "semantic" / "rotation_heatmap" / f"{trade_date}.json", heatmap_payload)
    return True


def _ensure_rotation_semantic_exists(trade_date: str) -> None:
    latest = ROOT / "data" / "semantic" / "rotation_latest" / f"{trade_date}.json"
    heat = ROOT / "data" / "semantic" / "rotation_heatmap" / f"{trade_date}.json"
    if latest.exists() and heat.exists():
        return
    ok = _backfill_semantic_from_cached_report(trade_date)
    if ok:
        print(json.dumps({"autobackfill": "applied", "trade_date": trade_date}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run rotation research wrapper for cron exec path.")
    parser.add_argument("--mode", default="prod", choices=["prod", "test"])
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--etf-pool", default="")
    parser.add_argument("--runner-timeout-seconds", type=int, default=1200)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=int, default=5)
    args = parser.parse_args()
    _load_env_file(ENV_PATH)

    trade_date = (args.trade_date or "").strip() or _today_shanghai()
    payload = {
        "etf_pool": args.etf_pool,
        "trade_date": trade_date,
        "lookback_days": args.lookback_days,
        "top_k": args.top_k,
        "mode": args.mode,
        # Keep cron path bounded: prioritize timely delivery over full online backfill.
        "max_runtime_seconds": 300.0,
        "retry_runtime_seconds": 120.0,
        "allow_online_backfill": False,
        "retry_allow_online_backfill": False,
    }
    cmd = [
        "/home/xie/etf-options-ai-assistant/.venv/bin/python",
        "/home/xie/etf-options-ai-assistant/tool_runner.py",
        "tool_send_etf_rotation_research_report",
        json.dumps(payload, ensure_ascii=False),
    ]

    attempts = max(1, int(args.max_retries))
    timeout_seconds = max(30, int(args.runner_timeout_seconds))
    backoff_seconds = max(1, int(args.retry_backoff_seconds))
    last_stdout = ""
    last_stderr = ""
    for idx in range(1, attempts + 1):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            last_stderr = "rotation_runner_timeout"
            if idx < attempts:
                time.sleep(backoff_seconds * idx)
                continue
            print(
                json.dumps(
                    {
                        "success": False,
                        "failure_code": "rotation_runner_timeout",
                        "attempts": attempts,
                    },
                    ensure_ascii=False,
                )
            )
            return 124

        last_stdout = (proc.stdout or "").strip()
        last_stderr = (proc.stderr or "").strip()
        if last_stdout:
            print(last_stdout)
        if last_stderr:
            print(last_stderr, file=sys.stderr)

        if proc.returncode != 0:
            if idx < attempts:
                time.sleep(backoff_seconds * idx)
                continue
            print(
                json.dumps(
                    {
                        "success": False,
                        "failure_code": "rotation_runner_nonzero_exit",
                        "attempts": attempts,
                        "exit_code": proc.returncode,
                    },
                    ensure_ascii=False,
                )
            )
            return proc.returncode

        try:
            result = json.loads(last_stdout)
        except Exception:
            print("invalid_json_output", file=sys.stderr)
            return 2

        if isinstance(result, dict) and result.get("success") is True:
            _ensure_rotation_semantic_exists(trade_date)
            return 0
        if idx < attempts:
            time.sleep(backoff_seconds * idx)
            continue
        print(
            json.dumps(
                {
                    "success": False,
                    "failure_code": "rotation_runner_unsuccessful_payload",
                    "attempts": attempts,
                },
                ensure_ascii=False,
            )
        )
        return 2

    print(last_stderr or "rotation_runner_failed", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
