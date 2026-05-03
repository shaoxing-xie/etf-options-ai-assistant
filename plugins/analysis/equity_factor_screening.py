"""
`tool_screen_equity_factors` 主实现位于 **openclaw-data-china-stock** 插件仓。

通过 ``plugins.china_stock_upstream`` 在加载上游模块时临时注入插件根路径，以便解析 ``plugins.utils.plugin_data_registry`` 等依赖。
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from plugins.china_stock_upstream import exec_upstream_module

_mod = exec_upstream_module("plugins/analysis/equity_factor_screening.py", "_ochina_equity_factor_screening")

tool_screen_equity_factors: Callable[..., Dict[str, Any]] = _mod.tool_screen_equity_factors
tool_screen_by_factors: Callable[..., Dict[str, Any]] = _mod.tool_screen_by_factors
_norm_code_6 = _mod._norm_code_6
