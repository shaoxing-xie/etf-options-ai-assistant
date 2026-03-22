"""静态配置（标的映射等）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


def load_symbol_mapping() -> Dict[str, Any]:
    """读取 `symbol_mapping.yaml`，供策略或工具解析 ETF↔指数↔期权标的。"""
    path = Path(__file__).resolve().parent / "symbol_mapping.yaml"
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}
