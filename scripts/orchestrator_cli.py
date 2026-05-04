#!/usr/bin/env python3
"""
任务编排 CLI：orchestrator_cli run <task_id> [--dry-run] [--trade-date YYYY-MM-DD] [--context JSON]

与 OpenClaw Cron 对齐：使用仓库根 .venv/bin/python 绝对路径 + bash -lc 加载 ~/.openclaw/.env（见 Cron 预检）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="etf-options-ai-assistant task orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="执行注册任务")
    pr.add_argument("task_id", type=str, help="tasks_registry.yaml 中的 task id")
    pr.add_argument("--dry-run", action="store_true", help="只解析 DAG，不执行子步骤")
    pr.add_argument("--trade-date", type=str, default="", help="非交易日调试：上一交易日 YYYY-MM-DD，注入 TRADE_DATE")
    pr.add_argument("--context", type=str, default="{}", help="JSON 对象，合并到执行 context（如 job 覆盖）")
    pr.add_argument(
        "--no-file-lock",
        action="store_true",
        help="跳过 Registry concurrency.file_lock（等价 context.skip_file_lock）",
    )
    pr.add_argument("--registry", type=str, default="", help="自定义 tasks_registry.yaml 路径")

    pl = sub.add_parser("list", help="列出已注册任务 id")
    pl.add_argument("--registry", type=str, default="", help="自定义 tasks_registry.yaml 路径")

    args = parser.parse_args()

    if args.cmd == "list":
        from src.orchestrator.registry import load_tasks_registry

        reg = load_tasks_registry(Path(args.registry) if args.registry else None)
        out = [
            {
                "id": tid,
                "enabled": t.enabled,
                "deprecated": t.deprecated,
                "replacement_task_id": t.replacement_task_id,
                "description": t.description,
                "steps": len(t.steps),
                "type": t.task_type,
            }
            for tid, t in sorted(reg.tasks.items())
        ]
        print(json.dumps({"success": True, "tasks": out}, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "run":
        from src.orchestrator.dag_executor import DAGExecutor
        from src.orchestrator.registry import load_tasks_registry

        try:
            ctx = json.loads(args.context) if args.context else {}
        except json.JSONDecodeError as e:
            print(json.dumps({"success": False, "error": f"invalid context json: {e}"}, ensure_ascii=False))
            return 2
        if not isinstance(ctx, dict):
            print(json.dumps({"success": False, "error": "context must be a json object"}, ensure_ascii=False))
            return 2
        if getattr(args, "no_file_lock", False):
            ctx["skip_file_lock"] = True

        reg = load_tasks_registry(Path(args.registry) if args.registry else None)
        ex = DAGExecutor(registry=reg)
        td = (args.trade_date or "").strip() or None
        res = ex.execute(
            args.task_id,
            context=ctx,
            trade_date=td,
            dry_run=bool(args.dry_run),
        )
        out = {
            "success": res.success,
            "task_id": res.task_id,
            "run_id": res.run_id,
            "message": res.message,
            "dependency_execution_order": res.dependency_execution_order,
            "steps": [
                {
                    "step_id": s.step_id,
                    "ok": s.ok,
                    "error": s.error,
                    "duration_ms": round(s.duration_ms, 2),
                    "output": s.output,
                }
                for s in res.steps
            ],
        }
        print(json.dumps(out, ensure_ascii=False, default=str))
        return 0 if res.success else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
