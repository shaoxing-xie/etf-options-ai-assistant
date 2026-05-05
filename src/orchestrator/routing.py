"""步骤级条件路由：安全比较表达式（禁止 eval）；可选 JMESPath 扩展。"""

from __future__ import annotations

import re
from typing import Any

from src.orchestrator.registry import StepDef, TaskDef

_RE_CMP = re.compile(
    r"^\s*([a-zA-Z_][\w.]*)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$",
)


def build_routing_document(*, step_id: str, ok: bool, output: dict[str, Any]) -> dict[str, Any]:
    """供 `when` 表达式使用的根对象：ok / output / step_id。"""
    return {"ok": ok, "output": output, "step_id": step_id}


def _parse_literal(rhs: str) -> Any:
    s = rhs.strip()
    if s.startswith("`") and s.endswith("`") and len(s) >= 2:
        return s[1:-1]
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    sl = s.lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    if sl == "null":
        return None
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _get_output_path(output: dict[str, Any], path: str) -> tuple[Any, bool]:
    cur: Any = output
    if not path:
        return cur, True
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def _compare(left: Any, right: Any, op: str) -> bool:
    try:
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == ">":
            return left > right  # type: ignore[operator]
        if op == "<":
            return left < right  # type: ignore[operator]
        if op == ">=":
            return left >= right  # type: ignore[operator]
        if op == "<=":
            return left <= right  # type: ignore[operator]
    except Exception:
        return False
    return False


def _safe_comparison_match(expr: str, document: dict[str, Any]) -> bool:
    m = _RE_CMP.match(expr)
    if not m:
        return False
    lhs, op, rhs_raw = m.group(1), m.group(2), m.group(3)
    rhs = _parse_literal(rhs_raw)
    if lhs == "ok":
        return _compare(document.get("ok"), rhs, op)
    if lhs == "step_id":
        return _compare(document.get("step_id"), rhs, op)
    if not lhs.startswith("output."):
        return False
    path = lhs[len("output.") :]
    out = document.get("output")
    if not isinstance(out, dict):
        return op == "!="
    left, found = _get_output_path(out, path)
    if not found:
        return op == "!="
    return _compare(left, rhs, op)


def routing_condition_matches(when: str, document: dict[str, Any]) -> bool:
    """
    求值 `when`：仅支持安全比较语法（禁止 eval / 禁止依赖 JMESPath 对 `==` 的歧义解析）。
    示例：output.quality_status == error、output.success == false、ok == true、step_id == foo
    """
    expr = (when or "").strip()
    if not expr:
        return False
    return _safe_comparison_match(expr, document)


def resolve_routing_target(task: TaskDef, source_step_id: str, document: dict[str, Any]) -> str | None:
    """
    返回 routing 规则匹配的下一 step id；无规则或无条件命中则返回 None（由调用方走顺序默认）。
    """
    for rule in task.routing:
        if not isinstance(rule, dict):
            continue
        if str(rule.get("source_step") or "") != source_step_id:
            continue
        for cond in rule.get("conditions") or []:
            if not isinstance(cond, dict):
                continue
            w = cond.get("when")
            if w and routing_condition_matches(str(w), document):
                t = cond.get("target")
                return str(t).strip() if t else None
        d = rule.get("default")
        if d is not None and str(d).strip():
            return str(d).strip()
    return None


def default_next_main_step(task: TaskDef, current_step_id: str) -> str | None:
    """主链 steps 顺序的下一 step；current 不在主链则返回 None。"""
    ids = [s.id for s in task.steps]
    try:
        i = ids.index(current_step_id)
    except ValueError:
        return None
    if i + 1 < len(ids):
        return ids[i + 1]
    return None


def resolve_next_step_id(
    task: TaskDef,
    *,
    current_step_id: str,
    step_ok: bool,
    output: dict[str, Any],
) -> str | None:
    """结合 routing 与主链顺序得到下一 step id；无下一步则 None。"""
    doc = build_routing_document(step_id=current_step_id, ok=step_ok, output=output)
    routed = resolve_routing_target(task, current_step_id, doc)
    if routed:
        return routed
    return default_next_main_step(task, current_step_id)


def merged_step_index(task: TaskDef) -> dict[str, StepDef]:
    """steps + branch_steps 索引；重复 id 以后者覆盖（应避免）。"""
    m: dict[str, StepDef] = {}
    for s in task.steps:
        m[s.id] = s
    for s in task.branch_steps:
        m[s.id] = s
    return m


def validate_step_graph(task: TaskDef) -> str | None:
    """若配置非法返回错误信息。"""
    if not task.steps:
        return None
    main_ids = {s.id for s in task.steps}
    for s in task.branch_steps:
        if s.id in main_ids:
            return f"branch_step_duplicates_main:{s.id}"
    idx = merged_step_index(task)
    for s in task.steps:
        if s.id not in idx:
            return f"missing_step:{s.id}"
    for s in task.branch_steps:
        if s.id not in idx:
            return f"missing_branch_step:{s.id}"
    for rule in task.routing:
        if not isinstance(rule, dict):
            continue
        src = str(rule.get("source_step") or "")
        if src and src not in idx:
            return f"routing_unknown_source:{src}"
        for cond in rule.get("conditions") or []:
            if not isinstance(cond, dict):
                continue
            t = cond.get("target")
            if t and str(t).strip() and str(t).strip() not in idx:
                return f"routing_unknown_target:{t}"
        d = rule.get("default")
        if d and str(d).strip() and str(d).strip() not in idx:
            return f"routing_unknown_default:{d}"
    return None
