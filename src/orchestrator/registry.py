from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def project_root() -> Path:
    return ROOT


@dataclass
class StepDef:
    id: str
    kind: str
    tool: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    argv_template: list[str] | None = None
    continue_on_failure: bool = False
    timeout_seconds: int | None = None
    # 从 execute(..., context=) 覆盖/注入同名键（如 monitor phase）
    params_from_context: tuple[str, ...] = ()


@dataclass
class TaskDef:
    id: str
    description: str = ""
    enabled: bool = True
    deprecated: bool = False
    replacement_task_id: str | None = None
    dependencies: list[str] = field(default_factory=list)
    quality_gates: list[dict[str, Any]] = field(default_factory=list)
    steps: list[StepDef] = field(default_factory=list)
    task_type: str = "dag"
    # 方案 §9：同刻争用 — file_lock 等
    concurrency: dict[str, Any] = field(default_factory=dict)


@dataclass
class TasksRegistry:
    version: str
    orchestrator_enabled: bool
    defaults: dict[str, Any]
    tasks: dict[str, TaskDef]


def _taskdefs_from_yaml_tasks(task_list: object) -> dict[str, TaskDef]:
    tasks: dict[str, TaskDef] = {}
    if not isinstance(task_list, list):
        return tasks
    for t in task_list:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or "").strip()
        if not tid:
            continue
        steps: list[StepDef] = []
        for s in t.get("steps") or []:
            if not isinstance(s, dict):
                continue
            pfc = s.get("params_from_context")
            pfc_t: tuple[str, ...] = ()
            if isinstance(pfc, list):
                pfc_t = tuple(str(x) for x in pfc if str(x).strip())
            steps.append(
                StepDef(
                    id=str(s.get("id") or "").strip() or "step",
                    kind=str(s.get("kind") or "tool").strip(),
                    tool=(str(s["tool"]) if s.get("tool") else None),
                    params=dict(s.get("params") or {}) if isinstance(s.get("params"), dict) else {},
                    argv_template=list(s["argv_template"]) if isinstance(s.get("argv_template"), list) else None,
                    continue_on_failure=bool(s.get("continue_on_failure", False)),
                    timeout_seconds=int(s["timeout_seconds"]) if s.get("timeout_seconds") is not None else None,
                    params_from_context=pfc_t,
                )
            )
        repl = t.get("replacement_task_id")
        repl_s = str(repl).strip() if repl else ""
        conc = t.get("concurrency") if isinstance(t.get("concurrency"), dict) else {}
        tasks[tid] = TaskDef(
            id=tid,
            description=str(t.get("description") or ""),
            enabled=bool(t.get("enabled", True)),
            deprecated=bool(t.get("deprecated", False)),
            replacement_task_id=repl_s or None,
            dependencies=[str(x) for x in (t.get("dependencies") or []) if x],
            quality_gates=list(t.get("quality_gates") or []) if isinstance(t.get("quality_gates"), list) else [],
            steps=steps,
            task_type=str(t.get("task_type") or "dag"),
            concurrency=dict(conc),
        )
    return tasks


def load_tasks_registry(path: Path | None = None) -> TasksRegistry:
    p = path or (ROOT / "config" / "tasks_registry.yaml")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("tasks_registry.yaml root must be a mapping")

    orch = raw.get("orchestrator") or {}
    enabled = bool(orch.get("enabled", True))
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        defaults = {}

    tasks = _taskdefs_from_yaml_tasks(raw.get("tasks") or [])

    # Cron 迁移任务：与主表合并（仅当未指定自定义 registry 路径时加载）
    if path is None:
        cron_yaml = ROOT / "config" / "tasks_registry.cron_jobs.yaml"
        if cron_yaml.exists():
            extra = yaml.safe_load(cron_yaml.read_text(encoding="utf-8"))
            if isinstance(extra, dict):
                tasks.update(_taskdefs_from_yaml_tasks(extra.get("tasks") or []))

    return TasksRegistry(
        version=str(raw.get("version") or "1"),
        orchestrator_enabled=enabled,
        defaults=defaults,
        tasks=tasks,
    )


def topological_order(task_ids: list[str], edges: dict[str, list[str]]) -> list[str]:
    """edges[A] = deps of A (must run first). Return order。"""
    seen: set[str] = set()
    order: list[str] = []

    def visit(nid: str) -> None:
        if nid in seen:
            return
        for d in edges.get(nid, []):
            visit(d)
        seen.add(nid)
        order.append(nid)

    for t in task_ids:
        visit(t)
    return order


GRAY, BLACK = "gray", "black"


def collect_task_dependency_closure(registry: TasksRegistry, goal: str) -> tuple[frozenset[str] | None, str | None]:
    """
    从 goal 沿 dependencies 收集全部必须先执行的任务 id；若存在环或未知依赖则返回 (None, message)。
    """
    if goal not in registry.tasks:
        return None, f"unknown_task:{goal}"
    state: dict[str, str] = {}
    nodes: set[str] = set()

    def visit(n: str) -> str | None:
        if n not in registry.tasks:
            return f"unknown_dependency:{n}"
        st = state.get(n)
        if st == BLACK:
            return None
        if st == GRAY:
            return "dependency_cycle"
        state[n] = GRAY
        for d in registry.tasks[n].dependencies:
            err = visit(d)
            if err:
                return err
        state[n] = BLACK
        nodes.add(n)
        return None

    err = visit(goal)
    if err:
        return None, err
    return frozenset(nodes), None


def topological_order_tasks(registry: TasksRegistry, nodes: frozenset[str]) -> tuple[list[str] | None, str | None]:
    """
    Kahn 拓扑排序：仅使用 nodes 内的边（task.dependencies）。
    若无法排满（环），返回 (None, dependency_cycle)。
    """
    in_deg: dict[str, int] = {n: 0 for n in nodes}
    for n in nodes:
        for d in registry.tasks[n].dependencies:
            if d in nodes:
                in_deg[n] += 1

    queue = [n for n in nodes if in_deg[n] == 0]
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in nodes:
            if n in registry.tasks[m].dependencies:
                in_deg[m] -= 1
                if in_deg[m] == 0:
                    queue.append(m)
    if len(order) != len(nodes):
        return None, "dependency_cycle"
    return order, None


def task_execution_plan(registry: TasksRegistry, goal: str) -> tuple[list[str] | None, str | None]:
    """返回按依赖顺序要执行的任务 id 列表（含 goal）。"""
    nodes, err = collect_task_dependency_closure(registry, goal)
    if err or nodes is None:
        return None, err or "collect_failed"
    return topological_order_tasks(registry, nodes)
