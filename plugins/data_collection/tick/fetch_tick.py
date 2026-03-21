"""
Tick 行情采集工具（供 etf_data_collector_agent 使用的示例实现）。

功能：
- 调用 tick_client.get_best_tick 获取标准化 Tick；
- 结合简单的规则生成“数据质量报告”；
- 为上层 Agent 提供一个单一入口，便于在工作流中使用。
"""

from __future__ import annotations

from typing import Any, Dict

from pathlib import Path
import sys

# 确保可以导入项目根目录下的 tick_client
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from tick_client import get_best_tick
except ImportError as exc:  # noqa: BLE001
    raise ImportError(f"无法导入 tick_client，请检查路径与安装: {exc}") from exc


def fetch_tick_with_quality(symbol: str = "000300") -> Dict[str, Any]:
    """
    为指定逻辑标的（默认 000300）获取 Tick 数据及质量报告。

    说明：
    - 本系统 Tick 功能目前仅支持指数/股票；
    - 当前配置中仅建议跟踪：000300.SH（沪深300）、399006.SZ（创业板指）。

    返回结构：
    {
      "symbol": "510300",
      "ok": true/false,
      "tick": {...} 或 None,
      "quality": {
        "tick_available": bool,
        "latency_ms": int 或 None,
        "provider": "itick" 等,
        "error": 错误字符串或 None,
      }
    }
    """
    config_path = str(ROOT / "config.yaml")
    result = get_best_tick(symbol, config_path=config_path)

    tick = result.get("tick")
    ok = bool(result.get("ok"))
    provider = result.get("provider")
    error = result.get("error")

    latency_ms = None
    if isinstance(tick, dict):
        latency_ms = tick.get("latency_ms")

    quality = {
        "tick_available": ok,
        "latency_ms": latency_ms,
        "provider": provider,
        "error": error,
    }

    return {
        "symbol": symbol,
        "ok": ok,
        "tick": tick,
        "quality": quality,
    }


__all__ = ["fetch_tick_with_quality"]

