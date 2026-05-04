from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from src.orchestrator.gate import apply_l4_gate
from src.orchestrator.registry import StepDef, TaskDef, TasksRegistry, load_tasks_registry, project_root, task_execution_plan
from src.orchestrator.resource_lock import advisory_file_lock
from src.orchestrator.run_record import write_task_run_v1


@dataclass
class StepResult:
    step_id: str
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    attempts: int = 1
    duration_ms: float = 0.0


@dataclass
class ExecutionResult:
    task_id: str
    run_id: str
    success: bool
    steps: list[StepResult] = field(default_factory=list)
    message: str = ""
    dependency_execution_order: list[str] = field(default_factory=list)


def _default_retry_cfg(defaults: dict[str, Any]) -> tuple[int, list[float]]:
    r = defaults.get("retry") or {}
    n = int(r.get("max_attempts", 3) or 3)
    delays = r.get("delays_seconds") or [15, 45, 90]
    dlist: list[float] = [float(x) for x in delays] if isinstance(delays, list) else [15.0, 45.0, 90.0]
    return max(1, n), dlist


def _expand_argv_template(
    argv_template: list[str],
    *,
    root: str,
    python_exe: str,
) -> list[str]:
    out: list[str] = []
    for a in argv_template:
        s = str(a)
        s = s.replace("{root}", root)
        s = s.replace("{python}", python_exe)
        out.append(s)
    return out


def _merge_step_params(step: StepDef, base_params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    out = dict(base_params)
    for k in step.params_from_context:
        if k in context and context[k] is not None:
            out[k] = context[k]
    return out


def _invoke_tool(tool_name: str, params: dict[str, Any], root: Path) -> dict[str, Any]:
    """通过 tool_runner 子进程调用，保证与 Cron 行为一致。"""

    tool_py = root / "tool_runner.py"
    cmd: list[str] = [sys.executable, str(tool_py), tool_name]
    if params:
        cmd.append(json.dumps(params, ensure_ascii=False))
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=3600,
    )
    raw = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if proc.returncode != 0:
        return {
            "success": False,
            "error": f"tool_exit_{proc.returncode}",
            "stderr": (proc.stderr or "")[-2000:],
            "stdout": (proc.stdout or "")[-2000:],
        }
    try:
        return json.loads(raw) if raw else {"success": True, "raw": ""}
    except json.JSONDecodeError:
        return {"success": bool(raw), "raw": raw}


def _run_step(
    step: Any,
    *,
    task: TaskDef,
    defaults: dict[str, Any],
    context: dict[str, Any],
    root: Path,
    trade_date_env: str | None,
    dry_run: bool,
) -> StepResult:
    t0 = time.perf_counter()
    sid = step.id
    max_attempts, delays = _default_retry_cfg(defaults)
    timeout_s = step.timeout_seconds or int(defaults.get("timeout_seconds") or 1800)

    attempt = 0
    last_err = ""
    while attempt < max_attempts:
        attempt += 1
        try:
            if dry_run:
                return StepResult(
                    sid,
                    True,
                    {"dry_run": True, "kind": step.kind},
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    attempts=attempt,
                )

            if step.kind == "tool":
                if not step.tool:
                    raise ValueError("tool step missing tool name")
                params = _merge_step_params(step, dict(step.params or {}), context)
                # context injection：B+C 采集管道（job / notify / throttle 等由 Cron --context 注入）
                if step.tool == "tool_run_data_cache_job":
                    if context.get("job"):
                        params = {**params, "job": str(context["job"])}
                    if "notify" in context:
                        params = {**params, "notify": bool(context["notify"])}
                    if "throttle_stock" in context:
                        params = {**params, "throttle_stock": bool(context["throttle_stock"])}
                    feishu = context.get("feishu_title")
                    if feishu is not None:
                        params = {**params, "feishu_title": str(feishu)}
                out = _invoke_tool(step.tool, params, root)
                ok = bool(out.get("success", True)) if isinstance(out, dict) else True
                return StepResult(
                    sid,
                    ok,
                    out if isinstance(out, dict) else {"result": out},
                    attempts=attempt,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )

            if step.kind == "exec":
                if not step.argv_template:
                    raise ValueError("exec step missing argv_template")
                argv = _expand_argv_template(
                    step.argv_template,
                    root=str(root),
                    python_exe=sys.executable,
                )
                env = os.environ.copy()
                if trade_date_env:
                    env["TRADE_DATE"] = trade_date_env
                    env["ASSISTANT_TRADE_DATE"] = trade_date_env
                proc = subprocess.run(
                    argv,
                    cwd=str(root),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                )
                ok = proc.returncode == 0
                payload = {
                    "exit_code": proc.returncode,
                    "stdout_tail": (proc.stdout or "")[-4000:],
                    "stderr_tail": (proc.stderr or "")[-4000:],
                }
                return StepResult(
                    sid,
                    ok,
                    payload,
                    error=None if ok else f"exit_{proc.returncode}",
                    attempts=attempt,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )

            raise ValueError(f"unknown step kind: {step.kind}")
        except subprocess.TimeoutExpired:
            last_err = "timeout"
        except Exception as e:
            last_err = str(e)

        if attempt < max_attempts:
            didx = min(attempt - 1, len(delays) - 1)
            time.sleep(max(0.1, delays[didx]))

    return StepResult(
        sid,
        False,
        {"error": last_err},
        error=last_err,
        attempts=max_attempts,
        duration_ms=(time.perf_counter() - t0) * 1000,
    )


def _goal_file_lock_path(
    goal: TaskDef,
    *,
    trade_date: str | None,
    context: dict[str, Any],
    root: Path,
) -> tuple[Path | None, float]:
    conc = goal.concurrency or {}
    if not conc.get("file_lock"):
        return None, 3600.0
    try:
        timeout_s = float(conc.get("lock_acquire_timeout_seconds", 3600))
    except (TypeError, ValueError):
        timeout_s = 3600.0
    td = str(trade_date or "na").replace(os.sep, "_")
    job = str(context.get("job") or context.get("profile") or "").replace(os.sep, "_")[:120]
    safe_tid = goal.id.replace(os.sep, "_").replace(" ", "")[:80]
    return (
        root / "data" / "meta" / "orchestrator_locks" / f"{safe_tid}_{td}_{job or 'default'}.lock",
        max(30.0, timeout_s),
    )


def _apply_quality_gates(task: TaskDef, ctx: dict[str, Any]) -> bool:
    ok = True
    for g in task.quality_gates:
        if not isinstance(g, dict):
            continue
        l4_key = str(g.get("l4_result_key") or "last_l4_result")
        l4r = ctx.get(l4_key)
        if isinstance(l4r, dict):
            decision = apply_l4_gate(l4r, g)
            if decision == "block":
                ok = False
    return ok


class DAGExecutor:
    def __init__(self, registry: TasksRegistry | None = None, registry_path: Any = None) -> None:
        self.registry = registry or load_tasks_registry(registry_path)

    def _run_single_task_steps(
        self,
        tid: str,
        *,
        ctx: dict[str, Any],
        root: Path,
        trade_date: str | None,
        dry_run: bool,
        on_step: Callable[[StepResult], None] | None,
        step_prefix: str,
    ) -> tuple[bool, list[StepResult]]:
        task = self.registry.tasks[tid]
        steps_out: list[StepResult] = []
        overall_ok = True
        for step in task.steps:
            sr = _run_step(
                step,
                task=task,
                defaults=self.registry.defaults,
                context=ctx,
                root=root,
                trade_date_env=trade_date,
                dry_run=dry_run,
            )
            out_sr = replace(sr, step_id=f"{step_prefix}{sr.step_id}") if step_prefix else sr
            steps_out.append(out_sr)
            if on_step:
                on_step(out_sr)

            if not sr.ok and not step.continue_on_failure:
                overall_ok = False
                break

        if overall_ok and not _apply_quality_gates(task, ctx):
            overall_ok = False
        return overall_ok, steps_out

    def execute(
        self,
        task_id: str,
        *,
        context: dict[str, Any] | None = None,
        trade_date: str | None = None,
        dry_run: bool = False,
        run_id: str | None = None,
        on_step: Callable[[StepResult], None] | None = None,
    ) -> ExecutionResult:
        ctx = dict(context or {})
        if ctx.get("profile") and not ctx.get("job"):
            ctx["job"] = ctx["profile"]
        tid = str(run_id or "").strip() or f"or_{uuid.uuid4().hex[:12]}"
        root = project_root()

        if not self.registry.orchestrator_enabled:
            return ExecutionResult(task_id, tid, False, message="orchestrator_disabled_in_registry")

        task = self.registry.tasks.get(task_id)
        if task is None:
            return ExecutionResult(task_id, tid, False, message=f"unknown_task:{task_id}")
        if not task.enabled:
            return ExecutionResult(task_id, tid, False, message=f"task_disabled:{task_id}")

        plan, perr = task_execution_plan(self.registry, task_id)
        if perr or plan is None:
            return ExecutionResult(task_id, tid, False, message=str(perr or "plan_failed"), steps=[])

        for pt in plan:
            if not self.registry.tasks[pt].enabled:
                return ExecutionResult(
                    task_id,
                    tid,
                    False,
                    message=f"dependency_disabled:{pt}",
                    steps=[],
                    dependency_execution_order=list(plan),
                )

        lock_path, lock_to = _goal_file_lock_path(task, trade_date=trade_date, context=ctx, root=root)
        use_lock = (
            lock_path is not None
            and not dry_run
            and not bool(ctx.get("skip_file_lock"))
        )
        lock_ctx = advisory_file_lock(lock_path, acquire_timeout_seconds=lock_to) if use_lock and lock_path else nullcontext()

        steps_out: list[StepResult] = []
        overall_ok = True

        try:
            with lock_ctx:
                for pt in plan:
                    prefix = f"{pt}::" if len(plan) > 1 else ""
                    ok, part = self._run_single_task_steps(
                        pt,
                        ctx=ctx,
                        root=root,
                        trade_date=trade_date,
                        dry_run=dry_run,
                        on_step=on_step,
                        step_prefix=prefix,
                    )
                    steps_out.extend(part)
                    if not ok:
                        overall_ok = False
                        break
        except TimeoutError as e:
            return ExecutionResult(
                task_id,
                tid,
                False,
                message=str(e),
                steps=steps_out,
                dependency_execution_order=list(plan),
            )

        payload = {
            "task_id": task_id,
            "run_id": tid,
            "success": overall_ok,
            "trade_date": trade_date,
            "dry_run": dry_run,
            "dependency_execution_order": list(plan),
            "steps": [
                {
                    "step_id": s.step_id,
                    "ok": s.ok,
                    "attempts": s.attempts,
                    "duration_ms": s.duration_ms,
                    "error": s.error,
                    "output_keys": list(s.output.keys()) if isinstance(s.output, dict) else [],
                }
                for s in steps_out
            ],
        }

        try:
            write_task_run_v1(payload, trade_date=trade_date)
        except OSError:
            pass

        return ExecutionResult(
            task_id=task_id,
            run_id=tid,
            success=overall_ok,
            steps=steps_out,
            message="" if overall_ok else "step_failed_or_gate_block",
            dependency_execution_order=list(plan),
        )


def preview_l4_gate_from_context(context: dict[str, Any], gate: dict[str, Any]) -> str:
    """测试用：对 context 中的 last_l4_result 应用门禁。"""
    lr = context.get("last_l4_result") or context.get("l4_result")
    if not isinstance(lr, dict):
        return "alert_only"
    return apply_l4_gate(lr, gate)
