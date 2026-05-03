"""上游 ``tool_plugin_catalog_digest``；勿放在 ``plugins/utils/`` 下以免提前锁定助手 ``plugins.utils`` 包。"""

from __future__ import annotations

from typing import Any, Callable, Dict

from plugins.china_stock_upstream import exec_upstream_module

_mod = exec_upstream_module("plugins/utils/catalog_digest_tool.py", "_ochina_catalog_digest_tool")

tool_plugin_catalog_digest: Callable[..., Dict[str, Any]] = _mod.tool_plugin_catalog_digest
