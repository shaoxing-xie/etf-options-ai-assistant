#!/usr/bin/env python3
"""
Parse OpenClaw cron JSONL for signal+risk inspection jobs and classify failures/quality.

Distinguishes:
- LLM: 403, timeout, All models failed, quota, rate limit
- DingTalk / keyword: summary/error mentioning dingtalk, 关键词, errcode 310000, Send Dingtalk
- anomaly summary ratio: non-structured summary / fake tool_call / garbled summary
- overlap skip: same job in-flight then skip(reason=already-running)

Usage:
  python3 scripts/triage_cron_signal_inspection.py
  python3 scripts/triage_cron_signal_inspection.py --runs-dir ~/.openclaw/cron/runs --days 14
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List


JOB_PREFIX = "etf-signal-risk-inspection"

LLM_MARKERS = (
    "403",
    "401",
    "429",
    "all models failed",
    "timed out",
    "timeout",
    "quota",
    "rate limit",
    "unauthorized",
    "forbidden",
    "insufficient_quota",
    "model overloaded",
    "provider unavailable",
)

DING_MARKERS = (
    "dingtalk",
    "钉钉",
    "关键词",
    "310000",
    "send dingtalk",
    "tool_send_dingtalk",
    "webhook",
    "errcode",
)

ANOMALY_PATTERNS = (
    re.compile(r"<tool_call>|<function|toolCall", re.IGNORECASE),
    re.compile(r"behavioral cloning|spring使用|zhihusearch|tencentcloud", re.IGNORECASE),
    re.compile(r"[\u0400-\u04FF]{4,}"),  # Cyrillic-like garbled chunks
    re.compile(r"[^\w\s]{6,}"),
)

ACK_KEYS = ("run_status", "run_quality", "phase", "degraded", "run_id", "ts")


def _tz_sh() -> timezone:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Asia/Shanghai")  # type: ignore[return-value]
    except Exception:
        return timezone(timedelta(hours=8))


def _classify(text: str) -> str:
    t = (text or "").lower()
    if any(m.lower() in t for m in LLM_MARKERS):
        return "llm"
    if any(m.lower() in t for m in DING_MARKERS):
        return "dingtalk_or_delivery"
    return "other_or_unknown"


def _iter_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not path.is_file():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _summary_is_ack_json(summary: str) -> bool:
    s = (summary or "").strip()
    if not s:
        return False
    if not (s.startswith("{") and s.endswith("}")):
        return False
    try:
        payload = json.loads(s)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    return all(k in payload for k in ACK_KEYS)


def _is_anomalous_summary(summary: str) -> bool:
    s = (summary or "").strip()
    if not s:
        return True
    if _summary_is_ack_json(s):
        return False
    if any(p.search(s) for p in ANOMALY_PATTERNS):
        return True
    # 非结构化自然语言默认计入异常（执行新 ACK 规范后的验收口径）
    return True


def _compute_overlap_skip(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    in_flight_starts = 0
    overlap_skip_count = 0
    for row in rows:
        action = str(row.get("action") or "")
        if action == "started":
            in_flight_starts += 1
        elif action == "finished":
            in_flight_starts = max(0, in_flight_starts - 1)
        elif action == "skipped":
            reason = str(row.get("reason") or "")
            if in_flight_starts > 0 and (
                reason == "already-running" or reason == "schedule-due-while-already-running"
            ):
                overlap_skip_count += 1
    return {
        "overlap_skip_count": overlap_skip_count,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Triage cron runs for signal+risk inspection jobs")
    ap.add_argument(
        "--runs-dir",
        default=os.path.expanduser("~/.openclaw/cron/runs"),
        help="Directory containing *.jsonl cron run logs",
    )
    ap.add_argument("--days", type=float, default=14.0, help="Only include runs newer than this many days")
    args = ap.parse_args()

    runs_dir = Path(args.runs_dir)
    tz = _tz_sh()
    cutoff = datetime.now(tz) - timedelta(days=args.days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    files = sorted(runs_dir.glob(f"{JOB_PREFIX}-*.jsonl"))
    if not files:
        print(f"No files matching {JOB_PREFIX}-*.jsonl under {runs_dir}")
        return

    by_job: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for fp in files:
        job_id = fp.stem
        for row in _iter_jsonl(fp):
            ts = row.get("runAtMs") or row.get("ts") or 0
            if ts and int(ts) < cutoff_ms:
                continue
            by_job[job_id].append(row)

    print(f"Runs dir: {runs_dir}")
    print(f"Window: last {args.days} days (since {cutoff.isoformat()})")
    print()

    for job_id in sorted(by_job.keys()):
        rows = sorted(by_job[job_id], key=lambda r: int(r.get("runAtMs") or r.get("ts") or 0))
        counts: Counter[str] = Counter()
        detail_llm = 0
        detail_ding = 0
        finished_total = 0
        anomalous_finished = 0
        for row in rows:
            status = row.get("status")
            err = row.get("error") or ""
            summary = row.get("summary") or ""
            blob = f"{err}\n{summary}"
            cat = _classify(blob)
            if status == "error":
                counts["status_error"] += 1
                if cat == "llm":
                    detail_llm += 1
                elif cat == "dingtalk_or_delivery":
                    detail_ding += 1
            elif status == "ok":
                counts["status_ok"] += 1
            else:
                counts[f"status_{status}"] += 1
            if str(row.get("action") or "") == "finished":
                finished_total += 1
                if _is_anomalous_summary(summary):
                    anomalous_finished += 1

        overlap = _compute_overlap_skip(rows)
        anomaly_ratio = (anomalous_finished / finished_total) if finished_total else 0.0

        print(f"=== {job_id} ({len(rows)} runs in window) ===")
        print(f"  status_ok: {counts.get('status_ok', 0)}  status_error: {counts.get('status_error', 0)}")
        if counts.get("status_error"):
            print(f"  errors classified (heuristic): llm-like={detail_llm}  dingtalk/delivery-like={detail_ding}")
        print(
            "  anomaly_summary_ratio: "
            f"{anomaly_ratio:.2%} ({anomalous_finished}/{finished_total})"
        )
        print(f"  overlap_skip_count: {overlap['overlap_skip_count']}")
        print()


if __name__ == "__main__":
    main()
