#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def _run_tool(repo_root: Path, payload: dict[str, Any], timeout_seconds: float) -> tuple[bool, dict[str, Any], int]:
    cmd = [
        str(repo_root / ".venv" / "bin" / "python"),
        str(repo_root / "tool_runner.py"),
        "tool_fetch_a_share_fund_flow",
        json.dumps(payload, ensure_ascii=False),
    ]
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_root), timeout=max(1.0, timeout_seconds))
    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return False, {"success": False, "message": "tool_runner_timeout"}, elapsed_ms
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    raw = (p.stdout or "").strip()
    try:
        out = json.loads(raw) if raw else {}
    except Exception:
        out = {"success": False, "message": raw or p.stderr or "invalid_json"}
    ok = bool(isinstance(out, dict) and out.get("success") is True)
    return ok, out if isinstance(out, dict) else {"success": False}, elapsed_ms


def _is_rate_limited(resp: dict[str, Any]) -> bool:
    msg = str(resp.get("message") or resp.get("error") or "").lower()
    markers = ("too many requests", "rate limit", "429", "限流", "throttle", "no tables found")
    return any(x in msg for x in markers)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual THS fund-flow rate-limit test matrix.")
    parser.add_argument("--repo-root", default="/home/xie/etf-options-ai-assistant")
    parser.add_argument("--batch-sizes", default="5,10,20")
    parser.add_argument("--sleep-seconds", default="0.5,1.0,2.0")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--backoff-first", type=float, default=1.0)
    parser.add_argument("--backoff-max", type=float, default=8.0)
    parser.add_argument("--output", default="")
    parser.add_argument("--tool-timeout-seconds", type=float, default=45.0)
    args = parser.parse_args()

    repo_root = Path(args.repo_root)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = (
        Path(args.output)
        if args.output
        else repo_root / "artifacts" / "ths_fund_flow_rate_limit" / f"manual_test_{ts}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    batches = [int(x) for x in args.batch_sizes.split(",") if x.strip()]
    sleeps = [float(x) for x in args.sleep_seconds.split(",") if x.strip()]
    periods = ["pre_open", "intraday", "after_close"]
    calls = [
        {"query_kind": "sector_rank", "sector_type": "industry", "rank_window": "immediate"},
        {"query_kind": "sector_rank", "sector_type": "concept", "rank_window": "immediate"},
        {"query_kind": "market_history", "max_days": 20},
    ]

    rows: list[dict[str, Any]] = []
    for period in periods:
        for batch_size in batches:
            for base_sleep in sleeps:
                req_total = 0
                succ = 0
                rate_hits = 0
                non_retryable = 0
                retry_count = 0
                retry_success = 0
                latencies: list[int] = []
                for _ in range(max(1, args.rounds)):
                    for i in range(batch_size):
                        payload = dict(calls[i % len(calls)])
                        payload["limit"] = 12
                        req_total += 1
                        ok, resp, latency = _run_tool(repo_root, payload, args.tool_timeout_seconds)
                        latencies.append(latency)
                        if ok:
                            succ += 1
                            time.sleep(base_sleep)
                            continue
                        if not _is_rate_limited(resp):
                            non_retryable += 1
                            time.sleep(base_sleep)
                            continue
                        rate_hits += 1
                        retry_ok = False
                        for r in range(max(0, args.retries)):
                            retry_count += 1
                            wait_s = min(args.backoff_first * (2**r), args.backoff_max)
                            time.sleep(wait_s)
                            rok, rresp, rlat = _run_tool(repo_root, payload, args.tool_timeout_seconds)
                            latencies.append(rlat)
                            if rok:
                                succ += 1
                                retry_success += 1
                                retry_ok = True
                                break
                            if not _is_rate_limited(rresp):
                                non_retryable += 1
                                break
                        if not retry_ok:
                            pass
                        time.sleep(base_sleep)
                p95 = sorted(latencies)[int((len(latencies) - 1) * 0.95)] if latencies else 0
                rows.append(
                    {
                        "period": period,
                        "batch_size": batch_size,
                        "sleep_seconds": base_sleep,
                        "request_total": req_total,
                        "success_count": succ,
                        "rate_limit_count": rate_hits,
                        "non_retryable_count": non_retryable,
                        "retry_count": retry_count,
                        "final_success_after_retry": retry_success,
                        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
                        "p95_latency_ms": p95,
                        "success_rate": round((succ / req_total), 6) if req_total else 0.0,
                    }
                )

    result = {
        "_meta": {
            "schema_name": "ths_fund_flow_rate_limit_manual_test_v1",
            "schema_version": "1.0.0",
            "generated_at": datetime.now().isoformat(),
            "task_id": "manual-ths-fund-flow-rate-limit",
            "quality_status": "ok",
        },
        "settings": {
            "rounds": args.rounds,
            "retries": args.retries,
            "backoff_first": args.backoff_first,
            "backoff_max": args.backoff_max,
            "batch_sizes": batches,
            "sleep_seconds": sleeps,
        },
        "rows": rows,
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "output": str(out_path), "rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
