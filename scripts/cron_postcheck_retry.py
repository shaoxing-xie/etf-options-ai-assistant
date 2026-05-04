#!/usr/bin/env python3
"""
Post-check cron task tool execution proof and retry once when missing.

Goal:
- Hard validation: require successful toolResult for the expected single tool call.
- Auto-compensation: retry exactly once per runAtMs when missing.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

def _run_json(cmd: list[str]) -> dict[str, Any]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        # Some openclaw subcommands may still print valid JSON on stdout for
        # non-zero exits (e.g. already-running). Accept that payload.
        try:
            maybe_json = json.loads(p.stdout)
            if isinstance(maybe_json, dict):
                return maybe_json
        except Exception:
            pass
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"invalid json from command: {' '.join(cmd)}\n{p.stdout}") from e


def _latest_finished(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    finished = [e for e in entries if e.get("action") == "finished"]
    if not finished:
        return None
    finished.sort(key=lambda e: int(e.get("runAtMs", 0) or 0), reverse=True)
    return finished[0]


def _is_target_tool_success(tool_result_message: dict[str, Any], expected_tool: str) -> bool:
    if tool_result_message.get("role") != "toolResult":
        return False
    tool_name = tool_result_message.get("toolName") or ""
    if tool_name != expected_tool:
        return False

    if tool_result_message.get("isError") is True:
        return False

    # Cron 统一 orchestrator_cli：外层仅一次 exec；成功以 exit=0 为主（details 结构因版本而异）
    if expected_tool == "exec":
        details = tool_result_message.get("details")
        if isinstance(details, dict):
            if details.get("exitCode") in (0, "0") or details.get("exit_code") in (0, "0"):
                return True
            if details.get("success") is True:
                return True
        text_fragments: list[str] = []
        for item in tool_result_message.get("content") or []:
            if item.get("type") != "text":
                continue
            text_fragments.append(str(item.get("text") or ""))
        merged = "\n".join(text_fragments)
        if '"success": true' in merged.replace(" ", "") or "'success': True" in merged:
            return True
        if "exitCode" in merged and ("exitCode\": 0" in merged or "exitCode\":0" in merged.replace(" ", "")):
            return True
        if "exit code: 0" in merged.lower():
            return True
        return False

    details = tool_result_message.get("details")
    if isinstance(details, dict):
        details_text = json.dumps(details, ensure_ascii=False)
        if "ERROR_NO_DELIVERY_TOOL_CALL" in details_text:
            return False
        if details.get("success") is True:
            response = details.get("response")
            if isinstance(response, dict):
                errcode = response.get("errcode")
                return errcode in (None, 0)
            return True
        if "success" in details and details.get("success") is False:
            return False

    has_explicit_success = False
    text_fragments: list[str] = []
    for item in tool_result_message.get("content") or []:
        if item.get("type") != "text":
            continue
        text = item.get("text") or ""
        text_fragments.append(str(text))
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if "success" in payload:
            has_explicit_success = True
        if payload.get("success") is True:
            response = payload.get("response")
            if isinstance(response, dict):
                errcode = response.get("errcode")
                return errcode in (None, 0)
            return True
        if payload.get("success") is False:
            return False
    merged_text = "\n".join(text_fragments)
    if "ERROR_NO_DELIVERY_TOOL_CALL" in merged_text:
        return False
    # Strict mode for cron delivery proof: no explicit success => not pass.
    return has_explicit_success is True


def _safe_slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text or "").strip())
    s = s.strip("_")
    return s or "na"


def _extract_context_field(message: str, field: str, default: str = "na") -> str:
    if not message:
        return default
    patterns = [
        rf"{field}\s*=\s*'([^']+)'",
        rf'{field}\s*=\s*"([^"]+)"',
        rf"{field}\s*=\s*([A-Za-z0-9_.-]+)",
    ]
    for p in patterns:
        m = re.search(p, message)
        if m:
            return str(m.group(1) or default)
    return default


def _build_compensation_key(
    *,
    job_id: str,
    run_at_ms: int,
    jobs_by_id: dict[str, dict[str, Any]],
    timezone_name: str,
) -> str:
    job = jobs_by_id.get(job_id) or {}
    payload = job.get("payload") or {}
    message = str(payload.get("message") or "")
    trade_date = _day_str_from_ms(run_at_ms, timezone_name)
    monitor_point = _extract_context_field(message, "monitor_point", "na")
    bundle = _extract_context_field(message, "monitor_bundle", "na")
    profile = _extract_context_field(message, "workflow_profile", "legacy")
    return (
        f"{_safe_slug(job_id)}:"
        f"{_safe_slug(trade_date)}:"
        f"{_safe_slug(monitor_point)}:"
        f"{_safe_slug(bundle)}:"
        f"{_safe_slug(profile)}"
    )


def _load_jobs_by_id(jobs_json: Path) -> dict[str, dict[str, Any]]:
    if not jobs_json.exists():
        return {}
    try:
        payload = json.loads(jobs_json.read_text(encoding="utf-8"))
    except Exception:
        return {}
    jobs = payload.get("jobs") or []
    out: dict[str, dict[str, Any]] = {}
    for j in jobs:
        if not isinstance(j, dict):
            continue
        jid = str(j.get("id") or "").strip()
        if jid:
            out[jid] = j
    return out


def _find_session_file(home: Path, session_id: str) -> Path | None:
    exact_matches = list(home.glob(f".openclaw/agents/*/sessions/{session_id}.jsonl"))
    if exact_matches:
        return exact_matches[0]
    return None


def _has_target_tool_success(session_file: Path, expected_tool: str) -> bool:
    with session_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("type") != "message":
                continue
            msg = row.get("message") or {}
            if _is_target_tool_success(msg, expected_tool=expected_tool):
                return True
    return False


def _has_any_target_tool_success(session_file: Path, expected_tools: list[str]) -> bool:
    if not expected_tools:
        return False
    expected = set(expected_tools)
    with session_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("type") != "message":
                continue
            msg = row.get("message") or {}
            tool_name = str(msg.get("toolName") or "")
            if tool_name not in expected:
                continue
            if _is_target_tool_success(msg, expected_tool=tool_name):
                return True
    return False


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _sync_jobs_state_delivery(job_id: str, *, delivered: bool, delivery_status: str) -> None:
    """
    Best-effort state sync:
    cron runs may keep `delivered=false` when delivery.mode=none even if toolResult proves
    downstream delivery succeeded. Persist a truthful lastDeliveryStatus in jobs-state.json
    so operational status views don't keep reporting false negatives.
    """
    jobs_state_path = Path.home() / ".openclaw" / "cron" / "jobs-state.json"
    if not jobs_state_path.exists():
        return
    try:
        payload = json.loads(jobs_state_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    jobs = payload.get("jobs")
    if not isinstance(jobs, dict):
        return
    node = jobs.get(job_id)
    if not isinstance(node, dict):
        return
    state = node.get("state")
    if not isinstance(state, dict):
        state = {}
    state["lastDelivered"] = bool(delivered)
    state["lastDeliveryStatus"] = str(delivery_status or ("ok" if delivered else "not-delivered"))
    node["state"] = state
    node["updatedAtMs"] = int(time.time() * 1000)
    jobs[job_id] = node
    payload["jobs"] = jobs
    try:
        jobs_state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _send_feishu_alert(repo_root: Path, *, title: str, message: str) -> tuple[bool, str]:
    runner = repo_root / "tool_runner.py"
    py = repo_root / ".venv" / "bin" / "python"
    if not py.exists() or not runner.exists():
        return False, "missing python/tool_runner"
    cmd = [
        str(py),
        str(runner),
        "tool_send_feishu_message",
        json.dumps({"title": title, "message": message}, ensure_ascii=False),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_root))
    ok = p.returncode == 0
    tail = (p.stdout or p.stderr or "").strip()[-500:]
    return ok, tail


def _alert_delivery_state_mismatch(
    *,
    job_id: str,
    job: dict[str, Any] | None,
    latest: dict[str, Any],
    state: dict[str, Any],
    expected_tools: list[str],
) -> None:
    """
    Alert once per run when tool proof says delivered but cron run fields still indicate not-delivered.
    """
    delivered_flag = latest.get("delivered")
    delivery_status = str(latest.get("deliveryStatus") or "").strip().lower()
    is_mismatch = (delivered_flag is False) or (delivery_status in {"not-delivered", "not_delivered"})
    if not is_mismatch:
        return

    # When delivery.mode is explicitly "none", cron run fields are expected to remain
    # not-delivered even if downstream tools delivered successfully. Postcheck will
    # still sync jobs-state.json for truthful operational status, but should not
    # page/alert on this expected mismatch.
    try:
        delivery_mode = ((job or {}).get("delivery") or {}).get("mode")
    except Exception:
        delivery_mode = None
    if str(delivery_mode or "").strip().lower() == "none":
        return

    run_at_ms = int(latest.get("runAtMs", 0) or 0)
    state_key = f"delivery-mismatch-alert:{job_id}:{run_at_ms}"
    if state.get(state_key, {}).get("alerted") is True:
        return

    repo_root = Path("/home/xie/etf-options-ai-assistant")
    title = f"[cron-delivery-mismatch] {job_id}"
    msg = (
        f"job_id={job_id}\n"
        f"runAtMs={run_at_ms}\n"
        f"sessionId={latest.get('sessionId')}\n"
        f"cron.delivered={latest.get('delivered')}\n"
        f"cron.deliveryStatus={latest.get('deliveryStatus')}\n"
        f"tool_proof=success({','.join(expected_tools)})\n"
        "action=state synced to lastDelivered=true,lastDeliveryStatus=ok by postcheck"
    )
    sent_ok, sent_tail = _send_feishu_alert(repo_root, title=title, message=msg)
    state[state_key] = {
        "alerted": True,
        "alertedAtMs": int(time.time() * 1000),
        "jobId": job_id,
        "runAtMs": run_at_ms,
        "sent_ok": sent_ok,
        "sent_tail": sent_tail,
        "deliveryStatus": latest.get("deliveryStatus"),
        "delivered": latest.get("delivered"),
        "expected_tools": expected_tools,
    }


def _extract_tools_from_message(message: str) -> list[str]:
    if not message:
        return []
    found = re.findall(r"\btool_[A-Za-z0-9_]+", message)
    seen: set[str] = set()
    out: list[str] = []
    for t in found:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _extract_expected_tool_from_constraints(message: str) -> str | None:
    if not message:
        return None
    if "orchestrator_cli.py run" in message and "`exec`" in message:
        return "exec"
    # Prefer explicit "single required action" constraints and parse tool call forms.
    # Example: 只调用一次 `tool_xxx(...)`；禁止调用其它工具（包括 `tool_yyy`）。
    priority_patterns = [
        r"(?:唯一动作|硬约束)[^。\n]*?`(tool_[A-Za-z0-9_]+)\s*\(",
        r"(?:只调用一次|仅调用一次|only call once)[^。\n]*?`(tool_[A-Za-z0-9_]+)\s*\(",
        r"(?:唯一动作|硬约束)[^。\n]*?(tool_[A-Za-z0-9_]+)\s*\(",
        r"(?:只调用一次|仅调用一次|only call once)[^。\n]*?(tool_[A-Za-z0-9_]+)\s*\(",
    ]
    for pattern in priority_patterns:
        m = re.search(pattern, message, flags=re.IGNORECASE)
        if m:
            return m.group(1)

    # Fallback: if there is exactly one explicit call-style tool reference in message.
    call_style = re.findall(r"\b(tool_[A-Za-z0-9_]+)\s*\(", message)
    dedup: list[str] = []
    seen: set[str] = set()
    for t in call_style:
        if t not in seen:
            seen.add(t)
            dedup.append(t)
    if len(dedup) == 1:
        return dedup[0]
    return None


def _extract_required_send_tools(message: str) -> list[str]:
    if not message:
        return []
    patterns = [
        r"必须至少调用一次以下发送工具之一[:：]\s*([^\n]+)",
        r"优先顺序[:：]\s*([^\n]+)",
    ]
    tools: list[str] = []
    for p in patterns:
        for m in re.finditer(p, message):
            chunk = m.group(1)
            tools.extend(re.findall(r"(tool_[A-Za-z0-9_]+)", chunk))
    # Fallback: parse explicit backticked send tool names from message.
    if not tools:
        for t in re.findall(r"`(tool_[A-Za-z0-9_]+)`", message):
            if t.startswith("tool_send_") or "_and_send" in t or "dingtalk" in t or "feishu" in t:
                tools.append(t)
    dedup: list[str] = []
    seen: set[str] = set()
    for t in tools:
        if t not in seen:
            seen.add(t)
            dedup.append(t)
    return dedup


def _parse_csv_items(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in str(text or "").split(","):
        v = item.strip()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _discover_single_tool_jobs(jobs_json: Path) -> dict[str, str]:
    if not jobs_json.exists():
        return {}
    data = json.loads(jobs_json.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or []
    targets: dict[str, str] = {}
    for job in jobs:
        if not job.get("enabled", True):
            continue
        payload = job.get("payload") or {}
        if payload.get("kind") != "agentTurn":
            continue
        message = str(payload.get("message") or "")
        inferred = _extract_expected_tool_from_constraints(message)
        if inferred:
            jid = str(job.get("id") or "").strip()
            if jid:
                targets[jid] = inferred
            continue
        tools = _extract_tools_from_message(message)
        if len(tools) != 1:
            continue
        jid = str(job.get("id") or "").strip()
        if jid:
            targets[jid] = tools[0]
    return targets


def _discover_send_required_jobs(jobs_json: Path) -> dict[str, list[str]]:
    if not jobs_json.exists():
        return {}
    data = json.loads(jobs_json.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or []
    targets: dict[str, list[str]] = {}
    for job in jobs:
        if not job.get("enabled", True):
            continue
        payload = job.get("payload") or {}
        if payload.get("kind") != "agentTurn":
            continue
        message = str(payload.get("message") or "")
        required_send_tools = _extract_required_send_tools(message)
        if not required_send_tools:
            continue
        jid = str(job.get("id") or "").strip()
        if jid:
            targets[jid] = required_send_tools
    return targets


def _is_analysis_like_job(job: dict[str, Any]) -> bool:
    name = str(job.get("name") or "")
    desc = str(job.get("description") or "")
    payload = job.get("payload") or {}
    message = str(payload.get("message") or "")
    text = "\n".join([name, desc, message])

    positive_patterns = [
        r"分析",
        r"行情",
        r"实盘",
        r"盘前",
        r"盘后",
        r"报告",
        r"monitor",
        r"analysis",
        r"report",
        r"inspection",
    ]
    if not any(re.search(p, text, flags=re.IGNORECASE) for p in positive_patterns):
        return False

    negative_patterns = [
        r"\bguard\b",
        r"postcheck",
        r"retry",
        r"health",
        r"ops",
        r"audit",
        r"autofix",
    ]
    if any(re.search(p, text, flags=re.IGNORECASE) for p in negative_patterns):
        return False
    return True


def _discover_analysis_jobs(jobs_json: Path) -> dict[str, str]:
    if not jobs_json.exists():
        return {}
    data = json.loads(jobs_json.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or []
    targets: dict[str, str] = {}
    for job in jobs:
        if not job.get("enabled", True):
            continue
        payload = job.get("payload") or {}
        if payload.get("kind") != "agentTurn":
            continue
        jid = str(job.get("id") or "").strip()
        if not jid:
            continue
        if _is_analysis_like_job(job):
            targets[jid] = str(job.get("name") or jid)
    return targets


def _parse_int_set(token: str, *, min_v: int, max_v: int) -> set[int]:
    out: set[int] = set()
    token = (token or "").strip()
    if not token:
        return out
    for part in token.split(","):
        p = part.strip()
        if not p:
            continue
        if "-" in p:
            a, b = p.split("-", 1)
            try:
                aa, bb = int(a), int(b)
            except Exception:
                continue
            if aa > bb:
                aa, bb = bb, aa
            for x in range(max(min_v, aa), min(max_v, bb) + 1):
                out.add(x)
        else:
            try:
                x = int(p)
            except Exception:
                continue
            if min_v <= x <= max_v:
                out.add(x)
    return out


def _is_single_time_field(token: str) -> bool:
    t = (token or "").strip()
    if not t:
        return False
    if any(ch in t for ch in ["*", "/", ",", "-"]):
        return False
    try:
        int(t)
        return True
    except Exception:
        return False


def _is_low_frequency_single_schedule(expr: str) -> bool:
    parts = [p for p in str(expr or "").split() if p]
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    if not (_is_single_time_field(minute) and _is_single_time_field(hour)):
        return False
    # Accept common low-frequency shapes:
    # - "20 9 * * 1-5" (daily weekdays once)
    # - "0 18 * * 5"  (weekly once)
    # - "0 9 15 * *"  (monthly once)
    allowed = set(["*", "?", "L"])
    dom_ok = dom in allowed or bool(_parse_int_set(dom, min_v=1, max_v=31))
    month_ok = month in ("*", "?") or bool(_parse_int_set(month, min_v=1, max_v=12))
    dow_ok = dow in ("*", "?") or bool(_parse_int_set(dow.replace("7", "0"), min_v=0, max_v=6))
    return dom_ok and month_ok and dow_ok


def _dow_matches(dow_expr: str, dt: datetime) -> bool:
    e = (dow_expr or "").strip()
    if e in ("*", "?"):
        return True
    # cron often uses 0/7=Sun,1=Mon...6=Sat. Python weekday(): Mon=0..Sun=6
    py_to_cron = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 0}
    cur = py_to_cron[dt.weekday()]
    expr = e.replace("7", "0")
    return cur in _parse_int_set(expr, min_v=0, max_v=6)


def _dom_matches(dom_expr: str, dt: datetime) -> bool:
    e = (dom_expr or "").strip()
    if e in ("*", "?"):
        return True
    return dt.day in _parse_int_set(e, min_v=1, max_v=31)


def _month_matches(month_expr: str, dt: datetime) -> bool:
    e = (month_expr or "").strip()
    if e in ("*", "?"):
        return True
    return dt.month in _parse_int_set(e, min_v=1, max_v=12)


def _single_schedule_due_lag_minutes(expr: str, timezone_name: str) -> int | None:
    parts = [p for p in str(expr or "").split() if p]
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    tz = ZoneInfo(timezone_name) if ZoneInfo else None
    now = datetime.now(tz=tz)
    try:
        hh = int(hour)
        mm = int(minute)
    except Exception:
        return None
    if not (_month_matches(month, now) and _dom_matches(dom, now) and _dow_matches(dow, now)):
        return None
    due_delta_minutes = (now.hour * 60 + now.minute) - (hh * 60 + mm)
    if due_delta_minutes < 0:
        return None
    return due_delta_minutes


def _discover_scheduled_single_jobs(jobs_json: Path) -> dict[str, tuple[str, str]]:
    if not jobs_json.exists():
        return {}
    data = json.loads(jobs_json.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or []
    out: dict[str, tuple[str, str]] = {}
    for job in jobs:
        if not job.get("enabled", True):
            continue
        payload = job.get("payload") or {}
        if payload.get("kind") != "agentTurn":
            continue
        sched = job.get("schedule") or {}
        if str(sched.get("kind") or "").strip().lower() != "cron":
            continue
        expr = str(sched.get("expr") or "").strip()
        if not _is_low_frequency_single_schedule(expr):
            continue
        jid = str(job.get("id") or "").strip()
        if not jid:
            continue
        jname = str(job.get("name") or jid)
        out[jid] = (jname, expr)
    return out


def _day_str_from_ms(run_at_ms: int, timezone_name: str) -> str:
    tz = ZoneInfo(timezone_name) if ZoneInfo else None
    dt = datetime.fromtimestamp(run_at_ms / 1000.0, tz=tz)
    return dt.strftime("%Y-%m-%d")


def _today_str(timezone_name: str) -> str:
    tz = ZoneInfo(timezone_name) if ZoneInfo else None
    return datetime.now(tz=tz).strftime("%Y-%m-%d")


def _has_executed_today(entries: list[dict[str, Any]], timezone_name: str) -> bool:
    today = _today_str(timezone_name)
    for e in entries:
        if e.get("action") not in ("started", "finished"):
            continue
        run_at_ms = int(e.get("runAtMs", 0) or 0)
        if run_at_ms <= 0:
            continue
        if _day_str_from_ms(run_at_ms, timezone_name) == today:
            return True
    return False


def _orch_has_terminal_succeeded_today(
    *,
    repo_root: Path,
    task_id: str,
    trade_date: str,
    trigger_window: str,
) -> bool:
    """
    Check L3 orchestration facts (append-only events) instead of cron-run entries.

    We consider "succeeded" as the only terminal success for the idempotency key.
    Skipped/failed do NOT satisfy the dependency chain.
    """
    events_file = repo_root / "data" / "decisions" / "orchestration" / "events" / f"{trade_date}.jsonl"
    if not events_file.is_file():
        return False
    idempotency_key = f"{task_id}:{trade_date}:{trigger_window}"
    try:
        with events_file.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                data = row.get("data") or {}
                if data.get("task_id") != task_id:
                    continue
                if data.get("idempotency_key") != idempotency_key:
                    continue
                if data.get("to_state") == "succeeded":
                    return True
    except Exception:
        return False
    return False


def _process_job(
    job_id: str,
    expected_tool: str,
    max_age_minutes: int,
    retry_timeout_ms: int,
    state: dict[str, Any],
    jobs_by_id: dict[str, dict[str, Any]],
    timezone_name: str,
) -> tuple[str, str]:
    runs = _run_json(["openclaw", "cron", "runs", "--id", job_id, "--limit", "20"])
    entries = runs.get("entries") or []
    latest = _latest_finished(entries)
    if not latest:
        return "skip", f"{job_id}: no finished entry found"

    run_at_ms = int(latest.get("runAtMs", 0) or 0)
    age_ms = int(time.time() * 1000) - run_at_ms
    if age_ms > max_age_minutes * 60 * 1000:
        return "skip", f"{job_id}: latest finished run too old (age_ms={age_ms})"

    session_id = str(latest.get("sessionId") or "").strip()
    if not session_id:
        return "fail", f"{job_id}: latest finished run missing sessionId"

    session_file = _find_session_file(Path.home(), session_id)
    if not session_file:
        return "fail", f"{job_id}: session file not found for sessionId={session_id}"

    if _has_target_tool_success(session_file, expected_tool=expected_tool):
        _alert_delivery_state_mismatch(
            job_id=job_id,
            job=jobs_by_id.get(job_id),
            latest=latest,
            state=state,
            expected_tools=[expected_tool],
        )
        _sync_jobs_state_delivery(job_id, delivered=True, delivery_status="ok")
        return "pass", f"{job_id}: toolResult success found for {expected_tool} ({session_file})"

    compensation_key = _build_compensation_key(
        job_id=job_id,
        run_at_ms=run_at_ms,
        jobs_by_id=jobs_by_id,
        timezone_name=timezone_name,
    )
    state_key = f"compensation:{compensation_key}"
    if state.get(state_key, {}).get("compensation_attempted") is True:
        return "fail", f"{job_id}: tool proof missing for {expected_tool}; compensation already consumed ({compensation_key})"

    retry_result = _run_json(
        [
            "openclaw",
            "cron",
            "run",
            job_id,
            "--expect-final",
            "--timeout",
            str(retry_timeout_ms),
        ]
    )
    if retry_result.get("ok") is True and retry_result.get("ran") is False and retry_result.get("reason") == "already-running":
        return "skip", f"{job_id}: retry skipped because job is already running"
    state[state_key] = {
        "retried": True,
        "compensation_attempted": True,
        "retriedAtMs": int(time.time() * 1000),
        "expectedTool": expected_tool,
        "compensationKey": compensation_key,
        "runAtMs": run_at_ms,
        "retryResult": retry_result,
    }
    return "retried", f"{job_id}: RETRY_QUEUED (missing tool proof for {expected_tool}, key={compensation_key})"


def _process_job_send_required(
    job_id: str,
    expected_send_tools: list[str],
    max_age_minutes: int,
    retry_timeout_ms: int,
    state: dict[str, Any],
    jobs_by_id: dict[str, dict[str, Any]],
    timezone_name: str,
) -> tuple[str, str]:
    runs = _run_json(["openclaw", "cron", "runs", "--id", job_id, "--limit", "20"])
    entries = runs.get("entries") or []
    latest = _latest_finished(entries)
    if not latest:
        return "skip", f"{job_id}: no finished entry found"

    run_at_ms = int(latest.get("runAtMs", 0) or 0)
    age_ms = int(time.time() * 1000) - run_at_ms
    if age_ms > max_age_minutes * 60 * 1000:
        return "skip", f"{job_id}: latest finished run too old (age_ms={age_ms})"

    session_id = str(latest.get("sessionId") or "").strip()
    if not session_id:
        return "fail", f"{job_id}: latest finished run missing sessionId"

    session_file = _find_session_file(Path.home(), session_id)
    if not session_file:
        return "fail", f"{job_id}: session file not found for sessionId={session_id}"

    if _has_any_target_tool_success(session_file, expected_tools=expected_send_tools):
        _alert_delivery_state_mismatch(
            job_id=job_id,
            job=jobs_by_id.get(job_id),
            latest=latest,
            state=state,
            expected_tools=expected_send_tools,
        )
        _sync_jobs_state_delivery(job_id, delivered=True, delivery_status="ok")
        return "pass", f"{job_id}: send toolResult success found in {expected_send_tools} ({session_file})"

    compensation_key = _build_compensation_key(
        job_id=job_id,
        run_at_ms=run_at_ms,
        jobs_by_id=jobs_by_id,
        timezone_name=timezone_name,
    )
    state_key = f"compensation:{compensation_key}"
    if state.get(state_key, {}).get("compensation_attempted") is True:
        return "fail", f"{job_id}: send proof missing; compensation already consumed ({compensation_key})"

    retry_result = _run_json(
        [
            "openclaw",
            "cron",
            "run",
            job_id,
            "--expect-final",
            "--timeout",
            str(retry_timeout_ms),
        ]
    )
    if retry_result.get("ok") is True and retry_result.get("ran") is False and retry_result.get("reason") == "already-running":
        return "skip", f"{job_id}: retry skipped because job is already running"
    state[state_key] = {
        "retried": True,
        "compensation_attempted": True,
        "retriedAtMs": int(time.time() * 1000),
        "expectedSendTools": expected_send_tools,
        "compensationKey": compensation_key,
        "runAtMs": run_at_ms,
        "retryResult": retry_result,
    }
    return "retried", f"{job_id}: RETRY_QUEUED (missing send proof in {expected_send_tools}, key={compensation_key})"


def _process_job_daily_catchup(
    job_id: str,
    job_name: str,
    timezone_name: str,
    retry_timeout_ms: int,
    state: dict[str, Any],
) -> tuple[str, str]:
    runs = _run_json(["openclaw", "cron", "runs", "--id", job_id, "--limit", "200"])
    entries = runs.get("entries") or []
    if _has_executed_today(entries, timezone_name):
        return "pass", f"{job_id}({job_name}): already executed today"

    today = _today_str(timezone_name)
    state_key = f"daily-catchup:{job_id}:{today}"
    if state.get(state_key, {}).get("triggered") is True:
        return "skip", f"{job_id}({job_name}): daily catch-up already triggered today"

    retry_result = _run_json(
        [
            "openclaw",
            "cron",
            "run",
            job_id,
            "--expect-final",
            "--timeout",
            str(retry_timeout_ms),
        ]
    )
    if retry_result.get("ok") is True and retry_result.get("ran") is False and retry_result.get("reason") == "already-running":
        return "skip", f"{job_id}({job_name}): catch-up skipped because job is already running"

    state[state_key] = {
        "triggered": True,
        "triggeredAtMs": int(time.time() * 1000),
        "jobName": job_name,
        "retryResult": retry_result,
    }
    return "retried", f"{job_id}({job_name}): DAILY_CATCHUP_TRIGGERED (no execution record today)"


def _process_job_scheduled_single_catchup(
    job_id: str,
    job_name: str,
    expr: str,
    timezone_name: str,
    max_age_minutes: int,
    retry_timeout_ms: int,
    state: dict[str, Any],
) -> tuple[str, str]:
    due_lag_minutes = _single_schedule_due_lag_minutes(expr, timezone_name)
    if due_lag_minutes is None:
        return "skip", f"{job_id}({job_name}): not due yet for schedule '{expr}'"
    if max_age_minutes > 0 and due_lag_minutes > max_age_minutes:
        return (
            "skip",
            f"{job_id}({job_name}): due but outside catch-up window "
            f"(lag={due_lag_minutes}m > max_age={max_age_minutes}m, expr='{expr}')",
        )

    runs = _run_json(["openclaw", "cron", "runs", "--id", job_id, "--limit", "200"])
    entries = runs.get("entries") or []
    if _has_executed_today(entries, timezone_name):
        return "pass", f"{job_id}({job_name}): already executed today"

    today = _today_str(timezone_name)
    state_key = f"scheduled-catchup:{job_id}:{today}"
    if state.get(state_key, {}).get("triggered") is True:
        return "skip", f"{job_id}({job_name}): scheduled catch-up already triggered today"

    retry_result = _run_json(
        [
            "openclaw",
            "cron",
            "run",
            job_id,
            "--expect-final",
            "--timeout",
            str(retry_timeout_ms),
        ]
    )
    if retry_result.get("ok") is True and retry_result.get("ran") is False and retry_result.get("reason") == "already-running":
        return "skip", f"{job_id}({job_name}): scheduled catch-up skipped because job is already running"

    state[state_key] = {
        "triggered": True,
        "triggeredAtMs": int(time.time() * 1000),
        "jobName": job_name,
        "expr": expr,
        "retryResult": retry_result,
    }
    return "retried", f"{job_id}({job_name}): SCHEDULED_SINGLE_CATCHUP_TRIGGERED (expr={expr})"


ORCHESTRATION_DEPENDENCY_RUNNERS: dict[str, dict[str, Any]] = {
    "pre-market-sentiment-check": {
        "depends_on": [],
        "trigger_window": "daily",
        "conditions": ["is_trading_day"],
        "command": "/home/xie/etf-options-ai-assistant/.venv/bin/python scripts/pre_market_sentiment_check_and_persist.py",
    },
    "strategy-calibration": {
        "depends_on": [],
        "trigger_window": "weekly",
        "conditions": ["is_trading_day"],
        "command": "/home/xie/etf-options-ai-assistant/.venv/bin/python scripts/strategy_calibration_and_persist.py",
    },
    "extreme-sentiment-monitor": {
        "depends_on": [],
        "trigger_window": "intraday-15m",
        "conditions": ["is_trading_day"],
        "command": "/home/xie/etf-options-ai-assistant/.venv/bin/python scripts/extreme_sentiment_monitor_and_persist.py",
    },
    "nightly-stock-screening": {
        "depends_on": [],
        "trigger_window": "daily",
        "conditions": ["is_trading_day", "position_ceiling_positive", "sentiment_stage_not_extreme", "emergency_pause_active"],
        "command": "/bin/bash -lc \"set -euo pipefail; /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/nightly_screening_and_persist.py; /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/persist_screening_semantic_snapshot.py\"",
    },
    "intraday-tail-screening": {
        "depends_on": [],
        "trigger_window": "intraday-30m",
        "conditions": ["is_trading_day", "emergency_pause_active", "sentiment_dispersion_low"],
        "command": "/bin/bash -lc \"set -euo pipefail; timeout 1500s /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/intraday_tail_screening_and_persist.py --max-candidates 50; /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/persist_screening_view_snapshot.py\"",
    },
    "position-tracking": {
        "depends_on": [],
        "trigger_window": "intraday-30m",
        "conditions": ["is_trading_day"],
        "command": "/home/xie/etf-options-ai-assistant/.venv/bin/python scripts/position_tracking_and_persist.py",
    },
    "weekly-selection-review": {
        "depends_on": [],
        "trigger_window": "weekly",
        "conditions": ["is_trading_day"],
        "command": "/home/xie/etf-options-ai-assistant/.venv/bin/python scripts/weekly_selection_review_and_persist.py",
    },
}


def _run_dependency_entrypoint(job_id: str, cfg: dict[str, Any], timeout_ms: int) -> tuple[bool, str]:
    timeout_sec = max(60, int(timeout_ms / 1000))
    depends_on = ",".join(cfg.get("depends_on") or [])
    conditions = ",".join(cfg.get("conditions") or [])
    command = str(cfg.get("command") or "").strip()
    cmd = (
        "set -euo pipefail; "
        "set -a; source /home/xie/.openclaw/.env || true; set +a; "
        "cd /home/xie/etf-options-ai-assistant; "
        "ORCH_TRIGGER_SOURCE=dependency "
        "/home/xie/etf-options-ai-assistant/.venv/bin/python scripts/orchestration_entrypoint.py "
        f"--task-id {job_id} "
        "--trigger-source dependency "
        f"--trigger-window {cfg.get('trigger_window') or 'daily'} "
        f"--depends-on \"{depends_on}\" "
        f"--conditions \"{conditions}\" "
        f"--timeout-seconds {min(300, timeout_sec)} "
        f"--command '{command}'"
    )
    p = subprocess.run(
        ["/bin/bash", "-lc", cmd],
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    msg = out if out else err
    return p.returncode == 0, msg[-800:]


def _process_job_dependency_catchup(
    job_id: str,
    timezone_name: str,
    retry_timeout_ms: int,
    state: dict[str, Any],
    max_attempts: int,
) -> tuple[str, str]:
    cfg = ORCHESTRATION_DEPENDENCY_RUNNERS.get(job_id)
    if not cfg:
        return "skip", f"{job_id}: no dependency runner config"
    repo_root = Path("/home/xie/etf-options-ai-assistant")
    trade_date = _today_str(timezone_name)
    trigger_window = str(cfg.get("trigger_window") or "daily")
    if _orch_has_terminal_succeeded_today(
        repo_root=repo_root,
        task_id=job_id,
        trade_date=trade_date,
        trigger_window=trigger_window,
    ):
        return "pass", f"{job_id}: already succeeded today (orchestration events)"
    runs = _run_json(["openclaw", "cron", "runs", "--id", job_id, "--limit", "200"])
    entries = runs.get("entries") or []
    if _has_executed_today(entries, timezone_name):
        # Note: cron-run can be 'ok' even when orchestration skipped; treat cron-run as weak signal.
        # If orchestration did not succeed, we still allow ONE dependency catch-up trigger per day.
        pass
    deps = cfg.get("depends_on") or []
    for dep in deps:
        dep_cfg = ORCHESTRATION_DEPENDENCY_RUNNERS.get(dep) or {}
        dep_window = str(dep_cfg.get("trigger_window") or "daily")
        if not _orch_has_terminal_succeeded_today(
            repo_root=repo_root,
            task_id=dep,
            trade_date=trade_date,
            trigger_window=dep_window,
        ):
            return "skip", f"{job_id}: upstream not ready ({dep})"
    state_key = f"dependency-catchup:{job_id}:{trade_date}"
    attempt_rec = state.get(state_key) if isinstance(state.get(state_key), dict) else {}
    attempts = int((attempt_rec or {}).get("attempts") or 0)
    if attempts >= max(1, max_attempts):
        return "skip", f"{job_id}: dependency catch-up attempts exhausted ({attempts}/{max_attempts})"
    ok, msg = _run_dependency_entrypoint(job_id, cfg, retry_timeout_ms)
    state[state_key] = {
        "triggered": True,
        "attempts": attempts + 1,
        "triggeredAtMs": int(time.time() * 1000),
        "ok": ok,
        "message_tail": msg,
    }
    if ok:
        return "retried", f"{job_id}: DEPENDENCY_CATCHUP_TRIGGERED (attempt {attempts + 1}/{max_attempts})"
    return "fail", f"{job_id}: dependency catch-up failed ({msg})"


ORCHESTRATION_ARTIFACT_GUARDS: dict[str, list[str]] = {
    # Critical outputs that must move forward when cron run claims success.
    "pre-market-sentiment-check": [
        "/home/xie/etf-options-ai-assistant/data/sentiment_check/{trade_date}.json",
        "/home/xie/etf-options-ai-assistant/data/semantic/sentiment_snapshot/{trade_date}.json",
    ],
    "strategy-calibration": [
        "/home/xie/etf-options-ai-assistant/data/decisions/signals/strategy_calibration_{trade_date}.json",
    ],
    "extreme-sentiment-monitor": [
        "/home/xie/etf-options-ai-assistant/data/decisions/risk/gate_events/extreme_sentiment_{trade_date}.json",
    ],
    "nightly-stock-screening": [
        "/home/xie/etf-options-ai-assistant/data/screening/{trade_date}.json",
        "/home/xie/etf-options-ai-assistant/data/decisions/recommendations/nightly_{trade_date}.json",
    ],
    "intraday-tail-screening": [
        "/home/xie/etf-options-ai-assistant/data/tail_screening/{trade_date}.json",
        "/home/xie/etf-options-ai-assistant/data/semantic/screening_view/{trade_date}.json",
    ],
    "position-tracking": [
        "/home/xie/etf-options-ai-assistant/data/decisions/watchlist/history/{trade_date}.json",
    ],
    "weekly-selection-review": [
        "/home/xie/etf-options-ai-assistant/data/screening/weekly_review.json",
    ],
}


def _process_orchestration_artifact_guard(
    *,
    job_id: str,
    trade_date: str,
    timezone_name: str,
    max_age_minutes: int,
    state: dict[str, Any],
) -> tuple[str, str]:
    paths_tpl = ORCHESTRATION_ARTIFACT_GUARDS.get(job_id) or []
    if not paths_tpl:
        return "skip", f"{job_id}: no artifact guard config"
    runs = _run_json(["openclaw", "cron", "runs", "--id", job_id, "--limit", "20"])
    entries = runs.get("entries") or []
    latest = _latest_finished(entries)
    if not latest:
        return "skip", f"{job_id}: no finished entry for artifact guard"
    if str(latest.get("status") or "").lower() != "ok":
        return "skip", f"{job_id}: latest status is not ok"
    run_at_ms = int(latest.get("runAtMs", 0) or 0)
    age_ms = int(time.time() * 1000) - run_at_ms
    if age_ms > max_age_minutes * 60 * 1000:
        return "skip", f"{job_id}: latest finished run too old for artifact guard"

    stale: list[str] = []
    for tpl in paths_tpl:
        p = Path(tpl.format(trade_date=trade_date))
        if not p.exists():
            stale.append(f"missing:{p}")
            continue
        mtime_ms = int(p.stat().st_mtime * 1000)
        if mtime_ms < run_at_ms:
            stale.append(f"stale:{p}")
    if not stale:
        return "pass", f"{job_id}: artifact freshness ok"

    state_key = f"artifact-guard-alert:{job_id}:{trade_date}:{run_at_ms}"
    if state.get(state_key, {}).get("alerted") is True:
        return "fail", f"{job_id}: artifact stale and already alerted ({','.join(stale)})"

    repo_root = Path("/home/xie/etf-options-ai-assistant")
    title = f"[artifact-guard] {job_id} cron=ok but artifact stale"
    msg = (
        f"job_id={job_id}\ntrade_date={trade_date}\nrunAtMs={run_at_ms}\n"
        f"timezone={timezone_name}\nissues={';'.join(stale)}\n"
        "action=manual rerun or inspect session logs"
    )
    sent_ok, sent_tail = _send_feishu_alert(repo_root, title=title, message=msg)
    state[state_key] = {
        "alerted": True,
        "alertedAtMs": int(time.time() * 1000),
        "issues": stale,
        "feishu_ok": sent_ok,
        "feishu_tail": sent_tail,
    }
    if sent_ok:
        return "fail", f"{job_id}: artifact stale alert sent ({','.join(stale)})"
    return "fail", f"{job_id}: artifact stale alert failed ({','.join(stale)})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cron tool post-check and one-shot retry.")
    parser.add_argument("--job-id", help="Cron job id to inspect and repair.")
    parser.add_argument("--tool-name", help="Expected single tool name for --job-id mode.")
    parser.add_argument(
        "--jobs-json",
        default=str(Path.home() / ".openclaw" / "cron" / "jobs.json"),
        help="jobs.json path for auto-discovery mode.",
    )
    parser.add_argument(
        "--auto-single-tool-tasks",
        action="store_true",
        help="Auto-discover enabled single-tool tasks from jobs.json and guard them all.",
    )
    parser.add_argument(
        "--auto-single-send-tasks",
        action="store_true",
        help="Backward-compatible alias of --auto-single-tool-tasks.",
    )
    parser.add_argument(
        "--auto-send-required-tasks",
        action="store_true",
        help="Auto-discover jobs that explicitly require at least one send tool call.",
    )
    parser.add_argument(
        "--auto-analysis-daily-catchup",
        action="store_true",
        help="Auto-discover analysis-like jobs and trigger once if no execution record exists today.",
    )
    parser.add_argument(
        "--auto-scheduled-single-catchup",
        action="store_true",
        help="Auto-discover low-frequency single cron jobs and trigger once if today's execution is missing.",
    )
    parser.add_argument(
        "--auto-orchestration-dependency-catchup",
        action="store_true",
        help="Use existing guard runner to trigger dependency-source orchestration for first DAG batch when upstream is ready.",
    )
    parser.add_argument(
        "--auto-orchestration-artifact-guard",
        action="store_true",
        help="Check critical orchestration artifacts freshness; alert when cron is ok but artifacts are stale/missing.",
    )
    parser.add_argument(
        "--dependency-catchup-max-attempts",
        type=int,
        default=3,
        help="Per-task max retry attempts per day for dependency catch-up mode.",
    )
    parser.add_argument(
        "--dependency-catchup-tasks",
        default="",
        help=(
            "Comma-separated task ids for dependency catch-up allowlist. "
            "When empty, all configured dependency tasks are eligible."
        ),
    )
    parser.add_argument(
        "--timezone",
        default="Asia/Shanghai",
        help="Timezone used by --auto-analysis-daily-catchup for 'today' determination.",
    )
    parser.add_argument("--max-age-minutes", type=int, default=60, help="Ignore runs older than this.")
    parser.add_argument("--retry-timeout-ms", type=int, default=120000, help="Timeout passed to cron run.")
    parser.add_argument(
        "--state-file",
        default=str(Path.home() / ".openclaw" / "cron" / "postcheck_retry_state.json"),
        help="Persistent state for idempotent one-shot retry.",
    )
    args = parser.parse_args()

    # Prevent concurrent postcheck runs from racing on state writes/alerts.
    lock_path = Path("/home/xie/.openclaw/cron/postcheck_retry_state.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fp = lock_path.open("w", encoding="utf-8")
    try:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("SKIP: another postcheck instance is running")
        return 0

    state_file = Path(args.state_file)
    state = _load_state(state_file)

    discovered = _discover_single_tool_jobs(Path(args.jobs_json))
    jobs_by_id = _load_jobs_by_id(Path(args.jobs_json))
    discovered_send_required = _discover_send_required_jobs(Path(args.jobs_json))
    discovered_analysis_jobs = _discover_analysis_jobs(Path(args.jobs_json))
    discovered_scheduled_single_jobs = _discover_scheduled_single_jobs(Path(args.jobs_json))
    targets: dict[str, str] = {}
    targets_send_required: dict[str, list[str]] = {}
    targets_daily_catchup: dict[str, str] = {}
    targets_scheduled_single_catchup: dict[str, tuple[str, str]] = {}
    targets_dependency_catchup: dict[str, dict[str, Any]] = {}
    targets_artifact_guard: dict[str, list[str]] = {}
    if args.auto_single_tool_tasks or args.auto_single_send_tasks:
        targets.update(discovered)
    if args.auto_send_required_tasks:
        targets_send_required.update(discovered_send_required)
    if args.auto_analysis_daily_catchup:
        targets_daily_catchup.update(discovered_analysis_jobs)
    if args.auto_scheduled_single_catchup:
        targets_scheduled_single_catchup.update(discovered_scheduled_single_jobs)
    if args.auto_orchestration_dependency_catchup:
        allow_tasks = _parse_csv_items(args.dependency_catchup_tasks)
        if allow_tasks:
            for task_id in allow_tasks:
                cfg = ORCHESTRATION_DEPENDENCY_RUNNERS.get(task_id)
                if isinstance(cfg, dict):
                    targets_dependency_catchup[task_id] = cfg
                else:
                    print(f"SKIP: unknown dependency catch-up task '{task_id}'")
        else:
            targets_dependency_catchup.update(ORCHESTRATION_DEPENDENCY_RUNNERS)
    if args.auto_orchestration_artifact_guard:
        targets_artifact_guard.update(ORCHESTRATION_ARTIFACT_GUARDS)
    if args.job_id:
        jid = args.job_id.strip()
        if jid:
            tool = (args.tool_name or discovered.get(jid) or "").strip()
            if not tool:
                print(f"FAIL: --tool-name required for --job-id {jid} when tool cannot be inferred")
                return 1
            targets[jid] = tool

    if (
        not targets
        and not targets_send_required
        and not targets_daily_catchup
        and not targets_scheduled_single_catchup
        and not targets_dependency_catchup
        and not targets_artifact_guard
    ):
        print("SKIP: no target jobs (use --job-id/--tool-name or auto discovery flags)")
        return 0

    had_fail = False
    had_retry = False
    for jid, tool in targets.items():
        status, msg = _process_job(
            job_id=jid,
            expected_tool=tool,
            max_age_minutes=args.max_age_minutes,
            retry_timeout_ms=args.retry_timeout_ms,
            state=state,
            jobs_by_id=jobs_by_id,
            timezone_name=args.timezone,
        )
        print(f"{status.upper()}: {msg}")
        if status == "fail":
            had_fail = True
        elif status == "retried":
            had_retry = True
    for jid, tools in targets_send_required.items():
        # Avoid double-processing jobs already covered by single-tool checks.
        if jid in targets:
            continue
        status, msg = _process_job_send_required(
            job_id=jid,
            expected_send_tools=tools,
            max_age_minutes=args.max_age_minutes,
            retry_timeout_ms=args.retry_timeout_ms,
            state=state,
            jobs_by_id=jobs_by_id,
            timezone_name=args.timezone,
        )
        print(f"{status.upper()}: {msg}")
        if status == "fail":
            had_fail = True
        elif status == "retried":
            had_retry = True
    for jid, jname in targets_daily_catchup.items():
        if jid in targets or jid in targets_send_required:
            continue
        status, msg = _process_job_daily_catchup(
            job_id=jid,
            job_name=jname,
            timezone_name=args.timezone,
            retry_timeout_ms=args.retry_timeout_ms,
            state=state,
        )
        print(f"{status.upper()}: {msg}")
        if status == "fail":
            had_fail = True
        elif status == "retried":
            had_retry = True
    for jid, payload in targets_scheduled_single_catchup.items():
        if jid in targets or jid in targets_send_required:
            continue
        jname, expr = payload
        status, msg = _process_job_scheduled_single_catchup(
            job_id=jid,
            job_name=jname,
            expr=expr,
            timezone_name=args.timezone,
            max_age_minutes=args.max_age_minutes,
            retry_timeout_ms=args.retry_timeout_ms,
            state=state,
        )
        print(f"{status.upper()}: {msg}")
        if status == "fail":
            had_fail = True
        elif status == "retried":
            had_retry = True
    for jid in targets_dependency_catchup.keys():
        if jid in targets or jid in targets_send_required:
            continue
        status, msg = _process_job_dependency_catchup(
            job_id=jid,
            timezone_name=args.timezone,
            retry_timeout_ms=args.retry_timeout_ms,
            state=state,
            max_attempts=args.dependency_catchup_max_attempts,
        )
        print(f"{status.upper()}: {msg}")
        if status == "fail":
            had_fail = True
        elif status == "retried":
            had_retry = True
    trade_date = _today_str(args.timezone)
    for jid in targets_artifact_guard.keys():
        status, msg = _process_orchestration_artifact_guard(
            job_id=jid,
            trade_date=trade_date,
            timezone_name=args.timezone,
            max_age_minutes=args.max_age_minutes,
            state=state,
        )
        print(f"{status.upper()}: {msg}")
        if status == "fail":
            had_fail = True

    _save_state(state_file, state)
    if had_fail:
        return 1
    if had_retry:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

