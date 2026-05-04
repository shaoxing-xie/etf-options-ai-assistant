#!/usr/bin/env python3
"""
对照「Cron → tasks_registry + orchestrator_cli」目标，扫描 jobs.json 并输出缺口表（Markdown）。

不修改 jobs；供评审与分阶段迁移。

用法:
  python scripts/inventory_cron_registry_gap.py --jobs ~/.openclaw/cron/jobs.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _sched_str(sched: object) -> str:
    if isinstance(sched, dict) and sched.get("kind") == "cron":
        return f"{sched.get('expr', '')} tz={sched.get('tz', '')}"
    return str(sched)


def _classify(msg: str, tools_allow: list[str]) -> tuple[str, str]:
    """(route_code, detail_snippet)"""
    if "orchestrator_cli.py" in msg or "orchestrator_cli.py run" in msg:
        return "orchestrator_cli", "tasks_registry"
    if "orchestration_entrypoint.py" in msg:
        m = re.search(r"--task-id\s+([a-zA-Z0-9_-]+)", msg)
        tid = m.group(1) if m else "?"
        return "orchestration_entrypoint", tid
    ts = ",".join(tools_allow) if tools_allow else ""
    exec_hint = "exec" in msg and (
        "只调用一次" in msg or "只能调用 exec" in msg or "exec.arguments" in msg
    )
    if "exec" in ts and exec_hint:
        if "run_data_cache_job_cli" in msg:
            m = re.search(r"--job\s+([a-zA-Z0-9_-]+)", msg)
            return "exec_data_cache_cli", (m.group(1) if m else "?")
        return "exec_other", ""
    if tools_allow and all(t != "exec" for t in tools_allow):
        return "agentTurn_mega_tool", tools_allow[0] if len(tools_allow) == 1 else ts[:60]
    return "agentTurn_other", ts[:80]


def _suggest_registry_task(route: str, detail: str, tool_id: str) -> str:
    if route == "orchestrator_cli":
        return "(已) daily_health 等 — 见 message"
    if route == "exec_data_cache_cli":
        return f'data_pipeline + context {{"job":"{detail}"}}'
    if route == "orchestration_entrypoint":
        return f"待合并: entrypoint:{detail} → tasks_registry"
    if route == "agentTurn_mega_tool":
        t = tool_id or detail
        if "signal_risk_inspection" in t:
            return 'unified_intraday + context {"phase":"…"}'
        if "opening_analysis" in t or "before_open" in t:
            return "unified_pre_open（Registry 展开后）"
        if "after_close" in t or "daily_report" in t:
            return "unified_after_close（Registry 展开后）"
        if "tail_session" in t:
            return "unified_intraday / 日经纳指子图（待建模）"
        if "midday_recap" in t:
            return "unified_pre_open 或独立 midday task（待建模）"
        return "待拆 Registry 单元（见 workflows 映射）"
    if route == "exec_other":
        return "逐脚本评审 → exec 步或专用 task_id"
    return "待分类"


def _meets_goal(route: str) -> str:
    return "是" if route == "orchestrator_cli" else "否"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=Path, default=Path.home() / ".openclaw" / "cron" / "jobs.json")
    args = ap.parse_args()
    raw = json.loads(args.jobs.read_text(encoding="utf-8"))
    jobs = raw.get("jobs") or []

    print("## Cron ↔ Registry 目标缺口表\n")
    print("| job_id | enabled | schedule | route | 说明/工具 | 建议 Registry 方向 | 满足核心原则 |")
    print("| --- | --- | --- | --- | --- | --- | --- |")

    for j in sorted(jobs, key=lambda x: (str(x.get("category", "")), str(x.get("name", "")))):
        pl = j.get("payload") or {}
        msg = str(pl.get("message") or "")
        tools = pl.get("toolsAllow") if isinstance(pl.get("toolsAllow"), list) else []
        route, detail = _classify(msg, tools)
        tool_id = tools[0] if tools and tools[0] != "exec" else ""
        suggest = _suggest_registry_task(route, detail, tool_id or detail)
        ok = _meets_goal(route)
        jid = str(j.get("id", ""))
        en = "是" if j.get("enabled", True) else "否"
        desc = detail if route in ("exec_data_cache_cli", "orchestration_entrypoint") else (tool_id or detail)[:48]
        print(
            f"| `{jid}` | {en} | {_sched_str(j.get('schedule'))} | {route} | {desc} | {suggest} | {ok} |"
        )

    total = len(jobs)
    done = sum(1 for j in jobs if "orchestrator_cli.py" in str((j.get("payload") or {}).get("message") or ""))
    print(f"\n**统计**: 共 {total} 条；**已 orchestrator_cli**（满足判据）: **{done}**；剩余 **{total - done}** 条需分阶段迁移或豁免登记。\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
