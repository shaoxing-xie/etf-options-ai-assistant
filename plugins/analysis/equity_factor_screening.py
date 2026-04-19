"""
`tool_screen_equity_factors` 主实现位于同级目录的 `openclaw-data-china-stock` 主仓。

本文件按路径动态加载，避免在助手仓重复维护一份因子引擎；部署时亦可通过 Gateway 插件包提供同名模块。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_UPSTREAM = (
    Path(__file__).resolve().parents[2].parent / "openclaw-data-china-stock" / "plugins" / "analysis" / "equity_factor_screening.py"
)


def _load_upstream() -> Any:
    if not _UPSTREAM.is_file():
        raise ImportError(
            f"未找到主仓实现 {_UPSTREAM}；请将 etf-options-ai-assistant 与 openclaw-data-china-stock 置于同级目录，"
            "或使用已安装含 `plugins.analysis.equity_factor_screening` 的 Gateway 插件。"
        )
    spec = importlib.util.spec_from_file_location(
        "_openclaw_equity_factor_screening_upstream",
        _UPSTREAM,
    )
    if spec is None or spec.loader is None:
        raise ImportError("无法加载 equity_factor_screening 规格")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_upstream()
tool_screen_equity_factors: Callable[..., Dict[str, Any]] = _mod.tool_screen_equity_factors
