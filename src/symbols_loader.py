"""
标的配置加载工具。

从项目内的 config/symbols.json 读取指数/ETF/期货/期权分组及 priority，
供 openclaw 工作流或本地脚本统一使用（如按 priority 拉取分钟/日线数据）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Literal, Any

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


SymbolsPriority = Literal["high", "medium", "low"]


@dataclass
class SymbolGroup:
  name: str
  description: str
  priority: SymbolsPriority
  index_codes: List[str]
  etf_codes: List[str]
  future_codes: List[str]
  option_underlyings: List[str]


def _get_symbols_config_path() -> Path:
  """
  统一定位 symbols.json 的路径。
  默认：项目根目录下的 config/symbols.json
  """
  project_root = Path(__file__).resolve().parents[1]
  return project_root / "config" / "symbols.json"


def load_symbols_config(path: Optional[str] = None) -> Dict[str, SymbolGroup]:
  """
  加载并解析 symbols.json，返回 {group_name: SymbolGroup}
  """
  cfg_path = Path(path) if path else _get_symbols_config_path()

  if not cfg_path.exists():
    logger.warning(f"symbols_loader: 配置文件不存在: {cfg_path}")
    return {}

  try:
    with cfg_path.open("r", encoding="utf-8") as f:
      raw: Dict[str, Any] = json.load(f)
  except Exception as e:
    logger.error(f"symbols_loader: 读取配置失败: {cfg_path}, error={e}")
    return {}

  groups_raw = (raw or {}).get("groups") or {}
  result: Dict[str, SymbolGroup] = {}

  for name, g in groups_raw.items():
    try:
      group = SymbolGroup(
        name=name,
        description=str(g.get("description") or ""),
        priority=(g.get("priority") or "medium"),  # type: ignore[arg-type]
        index_codes=list(g.get("index_codes") or []),
        etf_codes=list(g.get("etf_codes") or []),
        future_codes=list(g.get("future_codes") or []),
        option_underlyings=list(g.get("option_underlyings") or []),
      )
      result[name] = group
    except Exception as e:
      logger.error(f"symbols_loader: 解析分组失败: name={name}, error={e}")

  return result


def get_groups_by_priority(
  priority: SymbolsPriority,
  config: Optional[Dict[str, SymbolGroup]] = None,
) -> Dict[str, SymbolGroup]:
  """
  按 priority 过滤分组。
  """
  cfg = config or load_symbols_config()
  return {name: g for name, g in cfg.items() if g.priority == priority}


def get_all_codes_by_priority(
  priority: SymbolsPriority,
  config: Optional[Dict[str, SymbolGroup]] = None,
) -> Dict[str, List[str]]:
  """
  按 priority 聚合所有指数/ETF/期货/期权标的代码，便于上层批量采集。
  返回结构:
    {
      "index_codes": [...],
      "etf_codes": [...],
      "future_codes": [...],
      "option_underlyings": [...],
    }
  """
  cfg = config or load_symbols_config()
  result: Dict[str, List[str]] = {
    "index_codes": [],
    "etf_codes": [],
    "future_codes": [],
    "option_underlyings": [],
  }

  for g in cfg.values():
    if g.priority != priority:
      continue
    result["index_codes"].extend(g.index_codes)
    result["etf_codes"].extend(g.etf_codes)
    result["future_codes"].extend(g.future_codes)
    result["option_underlyings"].extend(g.option_underlyings)

  # 去重，保持顺序
  for key, codes in result.items():
    seen = set()
    deduped: List[str] = []
    for c in codes:
      if c not in seen:
        seen.add(c)
        deduped.append(c)
    result[key] = deduped

  return result


__all__ = [
  "SymbolsPriority",
  "SymbolGroup",
  "load_symbols_config",
  "get_groups_by_priority",
  "get_all_codes_by_priority",
]

