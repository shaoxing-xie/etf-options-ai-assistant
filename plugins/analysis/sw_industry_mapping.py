"""
申万行业映射：实现位于主仓 `openclaw-data-china-stock`（与 `equity_factor_screening` 同源）。

助手仓通过 `PYTHONPATH=.` 跑夜盘脚本时，主仓模块内的 `from plugins.analysis.sw_industry_mapping import …`
会解析到本包，故在此做动态加载，避免重复维护映射逻辑。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable, Optional, Tuple


def _candidate_paths() -> list[Path]:
    base = Path(__file__).resolve().parents[2]
    parent = base.parent
    out: list[Path] = []
    sibling = parent / "openclaw-data-china-stock" / "plugins" / "analysis" / "sw_industry_mapping.py"
    out.append(sibling)
    ext = Path.home() / ".openclaw" / "extensions" / "openclaw-data-china-stock" / "plugins" / "analysis" / "sw_industry_mapping.py"
    out.append(ext)
    return out


def _load_upstream() -> Any:
    for p in _candidate_paths():
        if not p.is_file():
            continue
        spec = importlib.util.spec_from_file_location("_openclaw_sw_industry_mapping_upstream", p)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    tried = ", ".join(str(p) for p in _candidate_paths())
    raise ImportError(
        "未找到 sw_industry_mapping 主仓实现。请将 openclaw-data-china-stock 与 etf-options-ai-assistant 置于同级目录，"
        f"或安装 ~/.openclaw/extensions/openclaw-data-china-stock。已尝试: {tried}"
    )


_mod = _load_upstream()
load_sw_level1_mapping: Callable[..., Tuple[dict[str, str], dict[str, Any]]] = _mod.load_sw_level1_mapping
industry_for_code: Callable[..., Optional[str]] = _mod.industry_for_code
mapping_stats: Callable[..., Tuple[int, int, float]] = _mod.mapping_stats
