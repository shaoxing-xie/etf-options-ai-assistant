"""
Locate **openclaw-data-china-stock** repo root and exec-load a single upstream module file.

Used when助手仓通过 symlink 引用了插件子树，但上游模块依赖 ``plugins.utils.*``（仅存在于插件仓根路径下）。
加载时在 ``exec_module`` 前后临时 ``sys.path.insert(0, repo_root)``，避免与助手仓 ``plugins.*`` 长期混排。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any


def resolve_openclaw_china_stock_root() -> Path | None:
    candidates: list[Path] = []
    env = os.environ.get("OPENCLAW_CHINA_STOCK_PLUGIN_ROOT")
    if env:
        candidates.append(Path(env))
    assistant_root = Path(__file__).resolve().parents[1]
    candidates.append(assistant_root.parent / "openclaw-data-china-stock")
    candidates.append(Path.home() / ".openclaw" / "extensions" / "openclaw-data-china-stock")

    for c in candidates:
        try:
            r = c.resolve()
        except Exception:
            continue
        marker = r / "plugins" / "utils" / "plugin_data_registry.py"
        if marker.is_file():
            return r
    return None


def exec_upstream_module(relative_path: str, unique_name: str) -> Any:
    """
    ``relative_path``: posix path relative to repo root, e.g. ``plugins/analysis/foo.py``.
    """
    root = resolve_openclaw_china_stock_root()
    if root is None:
        raise ImportError(
            "未解析到 openclaw-data-china-stock 根目录。请设置 OPENCLAW_CHINA_STOCK_PLUGIN_ROOT，"
            "或将插件仓置于助手同级目录，或安装到 ~/.openclaw/extensions/openclaw-data-china-stock。"
        )
    path = root / relative_path.replace("/", os.sep)
    if not path.is_file():
        raise ImportError(f"上游文件不存在: {path}")

    sroot = str(root)
    inserted = False
    if sroot not in sys.path:
        sys.path.insert(0, sroot)
        inserted = True
    try:
        spec = importlib.util.spec_from_file_location(unique_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法构建规格: {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if inserted:
            try:
                sys.path.remove(sroot)
            except ValueError:
                pass
