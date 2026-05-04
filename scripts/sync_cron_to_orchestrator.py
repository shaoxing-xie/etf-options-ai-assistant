#!/usr/bin/env python3
"""
将 ~/.openclaw/cron/jobs.json 中各任务迁移为：
  - 仓库内 config/tasks_registry.cron_jobs.yaml（每 job 一条 cron__<id> 任务）
  - jobs.json 仅保留单 exec：orchestrator_cli.py run cron__<id>

调度表达式/启用状态不改；执行语义由原 message 解析复刻（exec/bash、单 tool_runner、演化脚本、长 agent message 落盘）。

用法:
  /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/sync_cron_to_orchestrator.py --write-all
  # 仅生成仓库产物、不碰 jobs:
  /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/sync_cron_to_orchestrator.py --repo-only
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
DEFAULT_JOBS = Path.home() / ".openclaw" / "cron" / "jobs.json"
OUT_REGISTRY = REPO / "config" / "tasks_registry.cron_jobs.yaml"
OUT_MANIFEST = REPO / "config" / "cron_agent_payload_manifest.json"
OUT_MSG_DIR = REPO / "config" / "cron_agent_messages"

EVOLUTION_SHELL = {
    "factor-evolution-weekly": "factor",
    "strategy-evolution-weekly": "strategy",
}


def extract_balanced_brace(s: str, start: int) -> str | None:
    if start >= len(s) or s[start] != "{":
        return None
    depth = 0
    i = start
    in_str: str | None = None
    esc = False
    while i < len(s):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == in_str:
                in_str = None
            i += 1
            continue
        if c in ('"', "'"):
            in_str = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
        i += 1
    return None


def extract_exec_arguments_json(msg: str) -> dict[str, Any] | None:
    key = "exec.arguments="
    i = msg.find(key)
    if i < 0:
        return None
    j = msg.find("{", i)
    if j < 0:
        return None
    blob = extract_balanced_brace(msg, j)
    if not blob:
        return None
    try:
        out = json.loads(blob)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def extract_bash_after_marker(msg: str) -> str | None:
    for m in re.finditer(r"(?:^|\n)(/bin/bash -lc[^\n]+)", msg):
        line = m.group(1).strip()
        if "必须等待" in line:
            line = line.split("必须等待")[0].strip()
        elif "必须" in line and line.index("必须") < 200:
            line = line.split("必须")[0].strip()
        return line
    m = re.search(r"(?:command\*\*：|command：)\s*\n(/bin/bash -lc[^\n]+)", msg)
    if m:
        return m.group(1).strip()
    m = re.search(r"整行 \*\*command\*\*：\s*\n(/bin/bash -lc[^\n]+)", msg)
    if m:
        return m.group(1).strip()
    return None


def extract_yield_ms(msg: str, timeout_seconds: int) -> int:
    ej = extract_exec_arguments_json(msg)
    if isinstance(ej, dict):
        ym = ej.get("yieldMs")
        if isinstance(ym, (int, float)) and ym > 0:
            return int(ym)
    m = re.search(r"yieldMs\*\*（建议\s*\*?\*?(\d+)", msg)
    if m:
        return int(m.group(1))
    m = re.search(r"yieldMs\*\*[^\d]*(\d{5,})", msg)
    if m:
        return int(m.group(1))
    return max(300_000, int(timeout_seconds * 1000 * 2))


def scan_tool_call(msg: str) -> tuple[str, str] | None:
    m = re.search(r"(tool_run_[A-Za-z0-9_]+|tool_analyze_[A-Za-z0-9_]+)\s*\(", msg)
    if not m:
        return None
    tool = m.group(1)
    start = msg.find("(", m.start())
    depth = 0
    i = start
    in_str: str | None = None
    esc = False
    while i < len(msg):
        c = msg[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == in_str:
                in_str = None
            i += 1
            continue
        if c in ('"', "'"):
            in_str = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                inner = msg[start + 1 : i]
                return tool, inner
        i += 1
    return None


def _kw_value_to_python(node: ast.expr) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id == "true":
            return True
        if node.id == "false":
            return False
        if node.id == "null":
            return None
    return ast.literal_eval(node)


def kwargs_from_inner(inner: str) -> dict[str, Any]:
    inner = inner.strip()
    if not inner:
        return {}
    expr = ast.parse("f(" + inner + ")", mode="eval")
    call = expr.body
    assert isinstance(call, ast.Call)
    out: dict[str, Any] = {}
    for kw in call.keywords:
        if kw.arg:
            out[kw.arg] = _kw_value_to_python(kw.value)
    return out


def task_id_for_job(jid: str) -> str:
    return "cron__" + jid.replace("-", "_")


def classify_and_build_step(
    job: dict[str, Any],
) -> tuple[str, dict[str, Any], bool]:
    """
    Returns (step_kind, step_dict, needs_file_lock).
    step_dict is either {kind, tool, params} or {kind, argv_template} for yaml.
    """
    pl = job.get("payload") or {}
    msg = str(pl.get("message") or "")
    jid = str(job.get("id") or "")

    ej = extract_exec_arguments_json(msg)
    if isinstance(ej, dict) and isinstance(ej.get("command"), str):
        cmd = ej["command"]
        if cmd.strip().startswith("/bin/bash"):
            return (
                "exec",
                {
                    "id": "run",
                    "kind": "exec",
                    "argv_template": ["/bin/bash", "-lc", cmd],
                    "continue_on_failure": False,
                },
                "tool_run_data_cache_job" in cmd,
            )

    bash = extract_bash_after_marker(msg)
    if bash:
        return (
            "exec",
            {"id": "run", "kind": "exec", "argv_template": ["/bin/bash", "-lc", bash], "continue_on_failure": False},
            "tool_run_data_cache_job" in bash or "run_data_cache_job_cli" in bash,
        )

    if jid in EVOLUTION_SHELL:
        sub = EVOLUTION_SHELL[jid]
        inner = (
            f"set -euo pipefail; set -a; source /home/xie/.openclaw/.env || true; set +a; "
            f"cd {REPO} && ./scripts/evolution_workflows_dry_run.sh {sub}"
        )
        return (
            "exec",
            {"id": "run", "kind": "exec", "argv_template": ["/bin/bash", "-lc", inner], "continue_on_failure": False},
            False,
        )

    tc = scan_tool_call(msg)
    if tc:
        tool, inner = tc
        params = kwargs_from_inner(inner)
        return (
            "tool",
            {
                "id": "run",
                "kind": "tool",
                "tool": tool,
                "params": params,
                "continue_on_failure": False,
            },
            tool == "tool_run_data_cache_job",
        )

    # Agent freeform / multi-tool：由 run_openclaw_agent_cron_payload 执行
    return (
        "agent_payload",
        {
            "id": "run",
            "kind": "exec",
            "argv_template": [
                "{python}",
                str(REPO / "scripts/run_openclaw_agent_cron_payload.py"),
                "--job-id",
                jid,
            ],
            "continue_on_failure": False,
        },
        False,
    )


def build_uniform_cron_message(*, task_id: str, yield_ms: int, timeout_seconds: int) -> str:
    py = str(REPO / ".venv/bin/python")
    inner = (
        f"set -euo pipefail; set -a; source /home/xie/.openclaw/.env || true; set +a; "
        f'cd "{REPO}" && "{py}" scripts/orchestrator_cli.py run {task_id}'
    )
    cmd = "/bin/bash -lc " + json.dumps(inner, ensure_ascii=False)
    blob = json.dumps({"yieldMs": yield_ms, "command": cmd}, ensure_ascii=False)
    return (
        "【唯一动作（硬约束）】只调用一次 `exec`，禁止调用其它工具。\n"
        f"exec.arguments={blob}\n"
        "必须等待命令结束并按退出码回执：exit=0 仅回复「成功」；非0仅输出一行失败原因。"
        f"（payload.timeoutSeconds={timeout_seconds}）"
    )


def write_agent_payload(job: dict[str, Any]) -> None:
    jid = str(job.get("id") or "")
    pl = job.get("payload") or {}
    msg = str(pl.get("message") or "")
    OUT_MSG_DIR.mkdir(parents=True, exist_ok=True)
    safe = jid.replace("/", "_")
    rel = f"config/cron_agent_messages/{safe}.txt"
    path = REPO / rel
    path.write_text(msg, encoding="utf-8")


def _jobs_look_migrated(jobs: list[dict[str, Any]]) -> bool:
    """已迁移的 jobs 仅含 orchestrator_cli run cron__*；勿在其上再跑生成器（会从短 command 造出自引用任务）。"""
    n = 0
    hit = 0
    for job in jobs:
        pl = job.get("payload") or {}
        if pl.get("kind") != "agentTurn":
            continue
        n += 1
        msg = str(pl.get("message") or "")
        if "orchestrator_cli.py run cron__" in msg and "exec.arguments=" in msg:
            hit += 1
    return n > 0 and hit == n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=Path, default=DEFAULT_JOBS)
    ap.add_argument("--repo-only", action="store_true", help="只写仓库内 yaml/manifest/messages，不改 jobs.json")
    ap.add_argument("--write-all", action="store_true", help="写 registry + manifest + messages + 覆盖 jobs.json（先 .bak）")
    ap.add_argument(
        "--allow-regenerate-on-migrated-jobs",
        action="store_true",
        help="即使 jobs 已呈迁移后形态也重写 registry（仅当你从 jobs.json.bak 恢复后再生成时通常不需要此开关）",
    )
    args = ap.parse_args()

    if not args.write_all and not args.repo_only:
        print("Specify --write-all or --repo-only")
        return 2

    jobs_path: Path = args.jobs
    raw = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs: list[dict[str, Any]] = raw.get("jobs") or []

    if _jobs_look_migrated(jobs) and not args.allow_regenerate_on_migrated_jobs:
        print(
            "ERROR: jobs.json payloads look already migrated (orchestrator_cli run cron__).\n"
            "Regenerate tasks_registry.cron_jobs.yaml from a pre-migration copy (e.g. jobs.json.bak):\n"
            "  cp ~/.openclaw/cron/jobs.json.bak ~/.openclaw/cron/jobs.json\n"
            "then re-run with --repo-only / --write-all.\n"
            "Or pass --allow-regenerate-on-migrated-jobs if you intentionally accept self-referential tasks.",
        )
        return 3

    yaml_tasks: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {}

    for job in jobs:
        jid = str(job.get("id") or "").strip()
        if not jid:
            continue
        pl = job.get("payload") or {}
        if pl.get("kind") != "agentTurn":
            continue

        tid = task_id_for_job(jid)
        name = str(job.get("name") or jid)
        desc = str(job.get("description") or "")
        timeout_s = int(pl.get("timeoutSeconds") or 1800)
        msg = str(pl.get("message") or "")

        route, step, file_lock = classify_and_build_step(job)
        if route == "agent_payload":
            write_agent_payload(job)
            manifest[jid] = {
                "agent_id": str(job.get("agentId") or "etf_main"),
                "timeout_seconds": timeout_s,
                "thinking": str(pl.get("thinking") or "off"),
                "message_file": f"config/cron_agent_messages/{jid.replace('/', '_')}.txt",
            }

        step_yaml = dict(step)
        step_yaml["timeout_seconds"] = max(60, timeout_s)

        task_yaml: dict[str, Any] = {
            "id": tid,
            "description": f"cron mirror: {name} — {desc[:200]}",
            "enabled": bool(job.get("enabled", True)),
            "dependencies": [],
            "quality_gates": [],
            "steps": [step_yaml],
            "task_type": "dag",
        }
        if file_lock:
            task_yaml["concurrency"] = {"file_lock": True, "lock_acquire_timeout_seconds": min(7200, timeout_s + 600)}
        yaml_tasks.append(task_yaml)

    OUT_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    reg_doc = {
        "version": "1",
        "note": "Auto-generated by scripts/sync_cron_to_orchestrator.py — do not hand-edit unless you know the impact.",
        "tasks": yaml_tasks,
    }
    OUT_REGISTRY.write_text(
        yaml.safe_dump(reg_doc, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_REGISTRY} ({len(yaml_tasks)} tasks)")
    print(f"Wrote {OUT_MANIFEST} ({len(manifest)} agent payloads)")

    if args.write_all:
        bak = jobs_path.with_suffix(jobs_path.suffix + ".bak")
        shutil.copy2(jobs_path, bak)
        print(f"Backup jobs -> {bak}")
        for job in jobs:
            pl = job.get("payload") or {}
            if pl.get("kind") != "agentTurn":
                continue
            jid = str(job.get("id") or "").strip()
            tid = task_id_for_job(jid)
            to = int(pl.get("timeoutSeconds") or 1800)
            msg0 = str(pl.get("message") or "")
            ym = extract_yield_ms(msg0, to)
            pl["message"] = build_uniform_cron_message(task_id=tid, yield_ms=ym, timeout_seconds=to)
            pl["toolsAllow"] = ["exec"]
            if "lightContext" not in pl:
                pl["lightContext"] = True
        jobs_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Patched {jobs_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
