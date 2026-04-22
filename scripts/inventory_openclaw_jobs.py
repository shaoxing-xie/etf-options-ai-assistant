#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
JOBS_JSON = Path("/home/xie/.openclaw/cron/jobs.json")
TASK_MAP = ROOT / "data" / "meta" / "task_data_map.yaml"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_task_ids_from_task_map_yaml(text: str) -> set[str]:
    # 避免引入 yaml 依赖：只做最小解析（顶层 `tasks:` 下的 2 空格缩进 key）
    out: set[str] = set()
    in_tasks = False
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not in_tasks:
            if line.strip() == "tasks:":
                in_tasks = True
            continue
        if line and not line.startswith("  "):
            break
        if line.startswith("  ") and line.endswith(":") and (not line.startswith("    ")):
            key = line.strip().rstrip(":").strip()
            if key:
                out.add(key)
    return out


def _classify_job(job: dict[str, Any]) -> str:
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    tools = payload.get("toolsAllow") if isinstance(payload.get("toolsAllow"), list) else []
    msg = str(payload.get("message") or "")
    # 数据缓存采集：不是投研结论，但会影响上游取数
    if any(t == "tool_run_data_cache_job" for t in tools):
        return "data_cache_job"
    # 发送类：盘前/午评/尾盘/日报等
    if any("tool_run_" in t and t.endswith("_and_send") for t in tools) or "and_send" in msg:
        return "report_sender"
    # 其他 agentTurn：保守归类为 report_sender（多数为通知/巡检）
    return "report_sender"


def main() -> int:
    if not JOBS_JSON.is_file():
        raise SystemExit(f"missing: {JOBS_JSON}")

    task_ids = set()
    if TASK_MAP.is_file():
        task_ids = _read_task_ids_from_task_map_yaml(TASK_MAP.read_text(encoding="utf-8"))

    j = _read_json(JOBS_JSON)
    jobs = j.get("jobs") if isinstance(j.get("jobs"), list) else []
    out_jobs: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        tools = payload.get("toolsAllow") if isinstance(payload.get("toolsAllow"), list) else []
        name = job.get("name")
        job_id = job.get("id")
        enabled = bool(job.get("enabled"))
        category = _classify_job(job)
        out_jobs.append(
            {
                "id": job_id,
                "name": name,
                "enabled": enabled,
                "schedule": (job.get("schedule") or {}),
                "toolsAllow": tools,
                "category": category,
                "in_task_data_map": bool(name in task_ids or job_id in task_ids),
            }
        )

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload_out = {
        "generated_at": now,
        "source": str(JOBS_JSON),
        "stats": {
            "total_jobs": len(out_jobs),
            "enabled_jobs": sum(1 for x in out_jobs if x.get("enabled")),
            "by_category": {
                "data_cache_job": sum(1 for x in out_jobs if x.get("category") == "data_cache_job"),
                "report_sender": sum(1 for x in out_jobs if x.get("category") == "report_sender"),
            },
        },
        "jobs": out_jobs,
    }
    dest = ROOT / "data" / "meta" / f"openclaw_jobs_inventory_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    dest.write_text(json.dumps(payload_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "file": str(dest), "stats": payload_out["stats"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

