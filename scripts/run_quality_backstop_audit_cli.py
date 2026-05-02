#!/usr/bin/env python3
"""
定时质量兜底巡检：先跑 semantic_quality_backstop_audit.py（--no-notify），再发一条飞书摘要。

与 code-daily-health-check 相同思路：cron 仅单次 exec，避免多轮 LLM + tool_send 不稳定。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "bin" / "python"
AUDIT_SCRIPT = ROOT / "scripts" / "semantic_quality_backstop_audit.py"
SILENCE_FILE = ROOT / "data" / "meta" / "monitoring" / "semantic_alert_silence.json"
CRON_RUNS_DIR = Path("/home/xie/.openclaw/cron/runs")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        o = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return o if isinstance(o, dict) else {}


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


KV_ORDER = (
    "TEAM_RESULT",
    "FAILURE_CODES",
    "ROOT_CAUSE",
    "RISK",
    "AUTOFIX_ALLOWED",
    "EVIDENCE_REF",
    "TOP_ACTIONS",
)


def backstop_kv_from_report(report: dict[str, Any], report_path: Path) -> dict[str, str]:
    """供飞书摘要与 run_autofix_if_allowed 门禁对齐的键值（与 build_summary_lines 同源）。"""
    results = report.get("results") if isinstance(report.get("results"), list) else []
    alerts = report.get("alerts_emitted") if isinstance(report.get("alerts_emitted"), list) else []

    team = "TEAM_FAIL" if alerts else "TEAM_OK"
    codes: list[str] = []
    for it in alerts:
        if isinstance(it, dict):
            r = str(it.get("reason") or it.get("status") or "unknown")
            if r and r not in codes:
                codes.append(r)
    failure_codes = ",".join(codes) if codes else "NONE"

    risk = "LOW"
    for it in results:
        if not isinstance(it, dict):
            continue
        if str(it.get("status")) == "error" or it.get("failure_stage") == "snapshot":
            risk = "HIGH"
            break
    if risk == "LOW" and alerts:
        risk = "MEDIUM"

    autofix = "true" if risk == "LOW" else "false"
    root_cause = "语义层快照或质量门禁命中" if alerts else "未发现需即时告警项"

    top_actions: list[str] = []
    if alerts:
        top_actions.append("核对 alerts_emitted 对应数据集与 trade_date")
    if any(isinstance(x, dict) and x.get("stale") for x in results):
        top_actions.append("检查 stale 数据集的生成时间与流水线")
    if not top_actions:
        top_actions.append("保持常规监控")

    return {
        "TEAM_RESULT": team,
        "FAILURE_CODES": failure_codes,
        "ROOT_CAUSE": root_cause,
        "RISK": risk,
        "AUTOFIX_ALLOWED": autofix,
        "EVIDENCE_REF": str(report_path),
        "TOP_ACTIONS": ";".join(top_actions[:3]),
    }


def print_autofix_kv_footer(kv: dict[str, str]) -> None:
    """供 cron 会话 summary / 人读 stdout：run_autofix_if_allowed 也可改读语义 JSON。"""
    print("", flush=True)
    print("---BACKSTOP_KV_FOR_AUTOFIX---", flush=True)
    for k in KV_ORDER:
        print(f"{k}={kv.get(k, '')}", flush=True)


def _safe_pct(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return (numer / denom) * 100.0


def _collect_finished_events(day_start: datetime, day_end: datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not CRON_RUNS_DIR.is_dir():
        return events
    start_ms = int(day_start.timestamp() * 1000)
    end_ms = int(day_end.timestamp() * 1000)
    for p in CRON_RUNS_DIR.glob("*.jsonl"):
        try:
            raw = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("action") != "finished":
                continue
            ts = obj.get("ts")
            if not isinstance(ts, int) or ts < start_ms or ts >= end_ms:
                continue
            events.append(obj)
    return events


def _baseline_summary(today: datetime | None = None) -> list[str]:
    now = today or datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    yesterday_start = today_start - timedelta(days=1)
    tomorrow_start = today_start + timedelta(days=1)
    today_events = _collect_finished_events(today_start, tomorrow_start)
    yday_events = _collect_finished_events(yesterday_start, today_start)

    def _metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(events)
        ok = sum(1 for e in events if str(e.get("status")) == "ok")
        durations = [int(e.get("durationMs")) for e in events if isinstance(e.get("durationMs"), int)]
        avg_ms = int(sum(durations) / len(durations)) if durations else 0
        p95_ms = 0
        if durations:
            s = sorted(durations)
            idx = min(len(s) - 1, int(len(s) * 0.95))
            p95_ms = s[idx]
        counter: Counter[str] = Counter()
        for e in events:
            if str(e.get("status")) == "ok":
                continue
            reason = str(e.get("summary") or e.get("lastError") or "unknown_error").strip()
            counter[reason[:80]] += 1
        return {
            "total": total,
            "ok": ok,
            "success_rate": round(_safe_pct(ok, total), 1),
            "avg_ms": avg_ms,
            "p95_ms": p95_ms,
            "top_errors": counter.most_common(3),
        }

    mt = _metrics(today_events)
    my = _metrics(yday_events)
    lines = ["", "基线对比（cron 运行）:"]
    lines.append(
        f"- 今日 success={mt['success_rate']}% ({mt['ok']}/{mt['total']}), "
        f"avg={mt['avg_ms']}ms, p95={mt['p95_ms']}ms"
    )
    if my["total"] > 0:
        lines.append(
            f"- 昨日 success={my['success_rate']}% ({my['ok']}/{my['total']}), "
            f"avg={my['avg_ms']}ms, p95={my['p95_ms']}ms"
        )
        lines.append(
            f"- 变化 Δsuccess={round(mt['success_rate']-my['success_rate'],1)}pp, "
            f"Δavg={mt['avg_ms']-my['avg_ms']}ms, Δp95={mt['p95_ms']-my['p95_ms']}ms"
        )
    else:
        lines.append("- 昨日基线缺失：仅输出当日指标。")
    if mt["top_errors"]:
        tops = " | ".join([f"{msg} x{cnt}" for msg, cnt in mt["top_errors"]])
        lines.append(f"- 今日异常TopN: {tops}")
    else:
        lines.append("- 今日异常TopN: NONE")
    return lines


def _baseline_degradation_flags(today: datetime | None = None) -> list[str]:
    now = today or datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    yesterday_start = today_start - timedelta(days=1)
    tomorrow_start = today_start + timedelta(days=1)
    today_events = _collect_finished_events(today_start, tomorrow_start)
    yday_events = _collect_finished_events(yesterday_start, today_start)
    if not today_events or not yday_events:
        return []

    def _metrics(events: list[dict[str, Any]]) -> tuple[float, int]:
        total = len(events)
        ok = sum(1 for e in events if str(e.get("status")) == "ok")
        success_rate = _safe_pct(ok, total)
        durations = [int(e.get("durationMs")) for e in events if isinstance(e.get("durationMs"), int)]
        p95_ms = 0
        if durations:
            s = sorted(durations)
            idx = min(len(s) - 1, int(len(s) * 0.95))
            p95_ms = s[idx]
        return success_rate, p95_ms

    today_success, today_p95 = _metrics(today_events)
    yday_success, yday_p95 = _metrics(yday_events)
    flags: list[str] = []

    if (yday_success - today_success) > 3.0:
        flags.append(f"success_rate_drop>{3.0}pp")

    if yday_p95 > 0:
        rise_ratio = (today_p95 - yday_p95) / yday_p95
        if rise_ratio > 0.2:
            flags.append("p95_rise>20%")
    return flags


def build_summary_lines(
    report: dict[str, Any],
    report_path: Path,
    kv: dict[str, str] | None = None,
) -> tuple[str, str]:
    """(title, body) body 不含合并工具前缀。"""
    title = "质量兜底巡检（定时）"
    results = report.get("results") if isinstance(report.get("results"), list) else []
    alerts = report.get("alerts_emitted") if isinstance(report.get("alerts_emitted"), list) else []
    if kv is None:
        kv = backstop_kv_from_report(report, report_path)

    degrade_flags = _baseline_degradation_flags()
    has_degrade = bool(degrade_flags)
    lines = [
        "质量兜底巡检已完成（语义层 L4 快照抽检）。",
        "⚠️ 运行基线出现劣化，建议优先排查。" if has_degrade else "运行基线稳定，进入常规巡检节奏。",
        "",
        *[f"{k}={kv[k]}" for k in KV_ORDER],
        "",
        "数据集摘要:",
    ]
    for it in results[:12]:
        if not isinstance(it, dict):
            continue
        ds = it.get("dataset", "?")
        td = it.get("trade_date", "?")
        st = it.get("status", "?")
        rs = it.get("reason") or ""
        streak = it.get("degraded_streak", 0)
        stale = it.get("stale", False)
        tail = f" streak={streak}" if streak else ""
        tail += " stale" if stale else ""
        if rs:
            tail += f" ({rs})"
        lines.append(f"- {ds}@{td}: {st}{tail}")

    if alerts:
        lines.append("")
        lines.append("本次进入告警队列（已写入报告 alerts_emitted）:")
        for it in alerts[:8]:
            if isinstance(it, dict):
                lines.append(
                    f"- {it.get('dataset')}@{it.get('trade_date')}: "
                    f"{it.get('reason') or it.get('status')}"
                )
    if has_degrade:
        lines.append("")
        lines.append(f"劣化触发: {', '.join(degrade_flags)}")

    lines.extend(_baseline_summary())

    body = "\n".join(lines)
    if len(body) > 780:
        body = body[:777] + "..."
    return title, body


def _bump_silence_after_notify(alerts: list[Any]) -> None:
    if not alerts:
        return
    state = _read_json(SILENCE_FILE)
    now_ts = int(time.time())
    for it in alerts:
        if isinstance(it, dict):
            ds = it.get("dataset")
            if ds:
                state[str(ds)] = now_ts
    _save_json(SILENCE_FILE, state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Quality backstop audit + Feishu summary (cron-safe)")
    parser.add_argument("--no-notify", action="store_true", help="跳过飞书（仅跑审计脚本）")
    args = parser.parse_args()

    if not VENV_PY.is_file() or not AUDIT_SCRIPT.is_file():
        print(json.dumps({"success": False, "error": "missing venv or audit script"}, ensure_ascii=False))
        return 1

    proc = subprocess.run(
        [str(VENV_PY), str(AUDIT_SCRIPT), "--no-notify"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=600,
    )
    out = {"audit_exit": proc.returncode, "audit_stdout": (proc.stdout or "")[-1500:]}
    if proc.returncode != 0:
        out["success"] = False
        out["stderr"] = (proc.stderr or "")[-2000:]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = ROOT / "data" / "meta" / "monitoring" / f"semantic_quality_{today}.json"
    report = _read_json(report_path)
    if not report:
        out["success"] = False
        out["error"] = f"missing report: {report_path}"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1

    kv = backstop_kv_from_report(report, report_path)
    title, body = build_summary_lines(report, report_path, kv)
    out["report"] = str(report_path)
    out["feishu_title"] = title

    if args.no_notify:
        out["success"] = True
        out["notify_skipped"] = True
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print_autofix_kv_footer(kv)
        return 0

    sys.path.insert(0, str(ROOT))
    from plugins.merged.send_feishu_notification import tool_send_feishu_notification

    notify = tool_send_feishu_notification(
        "message",
        title=title,
        message=body,
        cooldown_minutes=0,
        cooldown_key=f"quality-backstop-audit:{today}",
    )
    out["notify_result"] = notify
    ok = bool(notify.get("success"))
    if ok:
        alerts = report.get("alerts_emitted") if isinstance(report.get("alerts_emitted"), list) else []
        _bump_silence_after_notify(alerts)
    out["success"] = ok
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print_autofix_kv_footer(kv)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
