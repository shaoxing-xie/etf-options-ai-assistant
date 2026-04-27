#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


RESEARCH_JOBS = [
    "etf-rotation-research",
    "factor-evolution-weekly",
    "strategy-evolution-weekly",
    "strategy-calibration",
    "weekly-selection-review",
]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def _run_quality(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").lower()
    if status == "error":
        return "error"
    summary = str(row.get("summary") or "")
    if "ERROR_NO_DELIVERY_TOOL_CALL" in summary:
        return "error"
    if status == "ok":
        return "ok_full"
    return "ok_degraded"


def _failure_code(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").lower()
    err = str(row.get("error") or "")
    summary = str(row.get("summary") or "")
    if "ERROR_NO_DELIVERY_TOOL_CALL" in summary:
        return "no_delivery_tool_call"
    if "timed out" in err.lower():
        return "timeout"
    if status == "error":
        return "runtime_error"
    if "duplicate_trigger" in summary:
        return "noop_duplicate_trigger"
    return "none"


def _calc_p(values: list[int], q: float) -> int:
    if not values:
        return 0
    seq = sorted(values)
    idx = int(round((len(seq) - 1) * q))
    return seq[max(0, min(idx, len(seq) - 1))]


def _job_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    finished = [x for x in entries if x.get("action") == "finished"]
    started = [x for x in entries if x.get("action") == "started"]
    skipped = [x for x in entries if x.get("action") == "skipped"]
    durations = [int(x.get("durationMs") or 0) for x in finished if isinstance(x.get("durationMs"), int)]
    quality_counts = {"ok_full": 0, "ok_degraded": 0, "error": 0}
    failure_counts: dict[str, int] = {}
    noop_count = 0
    for row in finished:
        q = _run_quality(row)
        quality_counts[q] = quality_counts.get(q, 0) + 1
        fc = _failure_code(row)
        if fc != "none":
            failure_counts[fc] = failure_counts.get(fc, 0) + 1
        if fc.startswith("noop_"):
            noop_count += 1
    return {
        "started_count": len(started),
        "finished_count": len(finished),
        "skipped_count": len(skipped),
        "quality_counts": quality_counts,
        "failure_counts": failure_counts,
        "noop_count": noop_count,
        "duration_ms": {
            "min": min(durations) if durations else 0,
            "p50": _calc_p(durations, 0.5),
            "p95": _calc_p(durations, 0.95),
            "max": max(durations) if durations else 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build 3-day baseline for research cron tasks.")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--runs-dir", default=str(Path.home() / ".openclaw" / "cron" / "runs"))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    now = datetime.now()
    now_ms = int(now.timestamp() * 1000)
    floor_ms = now_ms - int(max(1, args.days) * 24 * 3600 * 1000)

    jobs: dict[str, Any] = {}
    for job in RESEARCH_JOBS:
        path = runs_dir / f"{job}.jsonl"
        rows = _load_jsonl(path)
        within = [x for x in rows if int(x.get("runAtMs") or 0) >= floor_ms]
        jobs[job] = _job_summary(within)

    out = {
        "_meta": {
            "schema_name": "research_cron_baseline_v1",
            "schema_version": "1.0.0",
            "task_id": "etf_cron_research_agent",
            "run_id": now.strftime("%Y%m%dT%H%M%S"),
            "data_layer": "L4",
            "generated_at": now.isoformat(),
            "trade_date": now.strftime("%Y-%m-%d"),
            "source_tools": ["cron_runs_jsonl"],
            "lineage_refs": [str(runs_dir)],
            "quality_status": "ok",
        },
        "window_days": max(1, args.days),
        "jobs": jobs,
    }

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path("data/semantic/research_cron_baseline") / f"{now.strftime('%Y-%m-%d')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "output": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
