#!/usr/bin/env python3
"""
包装 `~/.openclaw/cron/run_autofix_if_allowed.py`：跑完后发一条飞书「已触发 / 已跳过 / 失败」摘要。

cron 仍保持单 exec；通知走合并工具，与 quality 巡检 CLI 一致。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "bin" / "python"
OPENCLAW_RUNNER = Path("/home/xie/.openclaw/cron/run_autofix_if_allowed.py")

KV_LINE = re.compile(
    r"^((?:BACKSTOP_)?(?:TEAM_RESULT|FAILURE_CODES|ROOT_CAUSE|RISK|AUTOFIX_ALLOWED|EVIDENCE_REF|TOP_ACTIONS)|BACKSTOP_KV_SOURCE)=(.*)$"
)


def _extract_kv_snippet(stdout: str, max_lines: int = 12) -> str:
    lines_out: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        m = KV_LINE.match(line)
        if m:
            lines_out.append(line)
        if len(lines_out) >= max_lines:
            break
    return "\n".join(lines_out) if lines_out else "（stdout 中无标准 KV 行）"


def classify_outcome(stdout: str, exit_code: int) -> tuple[str, str]:
    """(结果标签, 一行说明) — 结果标签 ∈ 已跳过|已触发|已触发（失败）|失败"""
    s = stdout
    if exit_code == 124 or "AUTOFIX_AGENT_EXIT_CODE=124" in s or "AUTOFIX_AGENT_TIMEOUT=" in s:
        return "失败", "openclaw agent 子进程超时（exit 124）"
    if "AUTOFIX_SKIPPED_NO_TODAY_AUDIT_RECORD" in s:
        return "已跳过", "当日窗口内无 quality-backstop-audit 的 finished 记录"
    if "NO_BACKSTOP_KV_IN_SUMMARY_OR_REPORT" in s:
        return "已跳过", "无法从 summary / semantic_quality 报告解析门禁 KV"
    if "NO_SUMMARY" in s:
        return "已跳过", "巡检记录无 summary 且未能从语义报告补全 KV"
    if "AUTOFIX_NOT_TRIGGERED" in s:
        return "已跳过", "未满足 TEAM_OK + RISK=LOW + AUTOFIX_ALLOWED=true，未调用 agent"
    if "AUTOFIX_TRIGGER_COMMAND=" in s:
        if exit_code == 0:
            return "已触发", "已调用 openclaw agent --local，进程退出码 0"
        return "已触发（失败）", f"已调用 openclaw agent，进程退出码 {exit_code}"
    if exit_code != 0:
        return "失败", f"run_autofix_if_allowed.py 退出码 {exit_code}"
    return "已跳过", "正常结束（未识别到触发/跳过标记，请查 stdout）"


def build_feishu_body(stdout: str, stderr: str, exit_code: int) -> tuple[str, str]:
    title = "质量兜底：autofix runner"
    tz = ZoneInfo("Asia/Shanghai")
    ts = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    label, reason = classify_outcome(stdout, exit_code)
    kv_snip = _extract_kv_snippet(stdout)
    tail = (stdout or "").strip()[-2500:]
    err_tail = (stderr or "").strip()[-1200:]
    parts = [
        f"（上海 {ts}）",
        "",
        f"执行结果：{label}",
        f"说明：{reason}",
        "",
        "门禁 / 关键输出摘录：",
        kv_snip,
        "",
        "--- run_autofix_if_allowed.py stdout（尾部）---",
        tail,
    ]
    if err_tail:
        parts.extend(["", "--- stderr（尾部）---", err_tail])
    body = "\n".join(parts)
    if len(body) > 3500:
        body = body[:3497] + "..."
    return title, body


def main() -> int:
    parser = argparse.ArgumentParser(description="Quality autofix runner + Feishu ack")
    parser.add_argument("--no-notify", action="store_true", help="仅跑 autofix 脚本，不发飞书")
    args = parser.parse_args()

    if not VENV_PY.is_file() or not OPENCLAW_RUNNER.is_file():
        print(json.dumps({"success": False, "error": "missing venv or openclaw runner"}, ensure_ascii=False))
        return 1

    proc = subprocess.run(
        [str(VENV_PY), str(OPENCLAW_RUNNER)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=1100,
    )
    out = {
        "autofix_exit": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-2000:],
    }
    label, _ = classify_outcome(proc.stdout or "", proc.returncode)
    out["outcome_label"] = label

    if args.no_notify:
        print(json.dumps({**out, "success": True, "notify_skipped": True}, ensure_ascii=False, indent=2))
        print(proc.stdout or "", end="")
        return proc.returncode

    sys.path.insert(0, str(ROOT))
    from plugins.merged.send_feishu_notification import tool_send_feishu_notification

    title, body = build_feishu_body(proc.stdout or "", proc.stderr or "", proc.returncode)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    notify = tool_send_feishu_notification(
        "message",
        title=title,
        message=body,
        cooldown_minutes=0,
        cooldown_key=f"quality-autofix-runner:{today}",
    )
    out["notify_result"] = notify
    feishu_ok = bool(notify.get("success"))
    out["feishu_ok"] = feishu_ok
    out["success"] = feishu_ok
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(proc.stdout or "", end="")
    if not feishu_ok:
        return 1
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
