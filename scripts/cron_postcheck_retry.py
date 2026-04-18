#!/usr/bin/env python3
"""
Post-check cron task tool execution proof and retry once when missing.

Goal:
- Hard validation: require successful toolResult for the expected single tool call.
- Auto-compensation: retry exactly once per runAtMs when missing.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

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

    details = tool_result_message.get("details")
    if isinstance(details, dict):
        if details.get("success") is True:
            response = details.get("response")
            if isinstance(response, dict):
                errcode = response.get("errcode")
                return errcode in (None, 0)
            return True
        if "success" in details and details.get("success") is False:
            return False

    has_explicit_success = False
    for item in tool_result_message.get("content") or []:
        if item.get("type") != "text":
            continue
        text = item.get("text") or ""
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
    # If no explicit success field is provided but toolResult exists and is not error,
    # treat it as executed successfully.
    return not has_explicit_success


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


def _process_job(
    job_id: str,
    expected_tool: str,
    max_age_minutes: int,
    retry_timeout_ms: int,
    state: dict[str, Any],
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
        return "pass", f"{job_id}: toolResult success found for {expected_tool} ({session_file})"

    state_key = f"{job_id}:{run_at_ms}"
    if state.get(state_key, {}).get("retried") is True:
        return "fail", f"{job_id}: tool proof missing for {expected_tool}; retry already consumed ({state_key})"

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
        "retriedAtMs": int(time.time() * 1000),
        "expectedTool": expected_tool,
        "retryResult": retry_result,
    }
    return "retried", f"{job_id}: RETRY_QUEUED (missing tool proof for {expected_tool})"


def _process_job_send_required(
    job_id: str,
    expected_send_tools: list[str],
    max_age_minutes: int,
    retry_timeout_ms: int,
    state: dict[str, Any],
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
        return "pass", f"{job_id}: send toolResult success found in {expected_send_tools} ({session_file})"

    state_key = f"{job_id}:{run_at_ms}"
    if state.get(state_key, {}).get("retried") is True:
        return "fail", f"{job_id}: send proof missing; retry already consumed ({state_key})"

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
        "retriedAtMs": int(time.time() * 1000),
        "expectedSendTools": expected_send_tools,
        "retryResult": retry_result,
    }
    return "retried", f"{job_id}: RETRY_QUEUED (missing send proof in {expected_send_tools})"


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
    parser.add_argument("--max-age-minutes", type=int, default=60, help="Ignore runs older than this.")
    parser.add_argument("--retry-timeout-ms", type=int, default=120000, help="Timeout passed to cron run.")
    parser.add_argument(
        "--state-file",
        default=str(Path.home() / ".openclaw" / "cron" / "postcheck_retry_state.json"),
        help="Persistent state for idempotent one-shot retry.",
    )
    args = parser.parse_args()

    state_file = Path(args.state_file)
    state = _load_state(state_file)

    discovered = _discover_single_tool_jobs(Path(args.jobs_json))
    discovered_send_required = _discover_send_required_jobs(Path(args.jobs_json))
    targets: dict[str, str] = {}
    targets_send_required: dict[str, list[str]] = {}
    if args.auto_single_tool_tasks or args.auto_single_send_tasks:
        targets.update(discovered)
    if args.auto_send_required_tasks:
        targets_send_required.update(discovered_send_required)
    if args.job_id:
        jid = args.job_id.strip()
        if jid:
            tool = (args.tool_name or discovered.get(jid) or "").strip()
            if not tool:
                print(f"FAIL: --tool-name required for --job-id {jid} when tool cannot be inferred")
                return 1
            targets[jid] = tool

    if not targets and not targets_send_required:
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
        )
        print(f"{status.upper()}: {msg}")
        if status == "fail":
            had_fail = True
        elif status == "retried":
            had_retry = True

    _save_state(state_file, state)
    if had_fail:
        return 1
    if had_retry:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

