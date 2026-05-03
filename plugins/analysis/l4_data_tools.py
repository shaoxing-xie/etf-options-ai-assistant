"""L4-data 工具：上游实现位于 openclaw-data-china-stock（见 ``plugins.china_stock_upstream``）。"""

from __future__ import annotations

from typing import Any, Callable, Dict

from plugins.china_stock_upstream import exec_upstream_module

_mod = exec_upstream_module("plugins/analysis/l4_data_tools.py", "_ochina_l4_data_tools")

tool_l4_valuation_context: Callable[..., Dict[str, Any]] = _mod.tool_l4_valuation_context
tool_l4_pe_ttm_percentile: Callable[..., Dict[str, Any]] = _mod.tool_l4_pe_ttm_percentile
