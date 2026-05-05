"""TypedDict 描述编排上下文（静态类型与文档；运行时为 dict）。"""

from __future__ import annotations

from typing import Any, TypedDict


class StepResultDoc(TypedDict, total=False):
    step_id: str
    ok: bool
    output: dict[str, Any]


class RoutingDocument(TypedDict, total=False):
    """传给 JMESPath `when` 的文档根。"""

    ok: bool
    output: dict[str, Any]
    step_id: str


class OrchestratorContext(TypedDict, total=False):
    last_step_result: StepResultDoc
    step_results: dict[str, StepResultDoc]
    memory_injection: str
    last_l4_result: dict[str, Any]
    skip_file_lock: bool
