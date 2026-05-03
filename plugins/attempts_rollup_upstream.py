"""上游 ``tool_summarize_attempts``；勿放在 ``plugins/utils/`` 下以免提前锁定助手 ``plugins.utils`` 包。"""

from __future__ import annotations

from typing import Any, Callable, Dict

from plugins.china_stock_upstream import exec_upstream_module

_mod = exec_upstream_module("plugins/utils/attempts_rollup.py", "_ochina_attempts_rollup")

tool_summarize_attempts: Callable[..., Dict[str, Any]] = _mod.tool_summarize_attempts
