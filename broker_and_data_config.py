"""
券商与数据源能力视图配置。

作用：
- 为上层 Agent 提供一个统一的“当前环境说明”，包括：
  - 券商 / 交易网关能力（是否已开通实盘、是否支持期权等）；
  - 数据源能力（是否有 Tick、分钟、日线、IV 等）；
  - 推断和假设（本地未明确配置时给出保守估计）。

设计：
- 使用简单的 Python 字典配置，方便在本地快速修改；
- 未来如果需要，也可以改为从独立 JSON / YAML 配置文件加载。
"""

from __future__ import annotations

import os
from typing import Any, Dict


def _default_broker_config() -> Dict[str, Any]:
    """
    默认券商配置（保守模式）。

    假设：
    - 仅用于回测 / 纸面仿真，不直接下真实订单；
    - 期权交易能力未知，默认为未开通。
    """
    execution_mode = os.getenv("ETF_EXECUTION_MODE", "signal_only").strip() or "signal_only"
    if execution_mode not in {"signal_only", "paper", "live"}:
        execution_mode = "signal_only"

    return {
        "name": "unspecified",
        "mode": "paper_only",  # one of: paper_only | live_supported
        "supports_live_trading": False,
        "supports_options": False,
        "execution_mode": execution_mode,
        "notes": [
            "当前未在本文件中显式声明券商名称与实盘能力，"
            "如果已经开通期权与实盘交易，请在此处补充配置。",
            "execution_mode 取自环境变量 ETF_EXECUTION_MODE（signal_only/paper/live），默认 signal_only。",
        ],
    }


def _default_data_feeds() -> Dict[str, Any]:
    """
    默认数据源能力（保守模式）。

    假设：
    - 策略开发阶段主要依赖 OpenClaw 内置 tool_fetch_* 与本地缓存；
    - Tick 与实时 IV 能力不做强假设，默认 False。
    """
    return {
        "etf_510300": {
            "symbol": "510300",
            "name": "沪深300ETF",
            "daily": True,
            "minute": True,
            "tick": False,
            "realtime": True,
        },
        "index_000300": {
            "symbol": "000300",
            "name": "沪深300指数",
            "daily": True,
            "minute": True,
            "tick": False,
            "realtime": True,
        },
        "index_399006": {
            "symbol": "399006",
            "name": "创业板指",
            "daily": True,
            "minute": True,
            "tick": False,
            "realtime": True,
        },
        "index_CNXA50": {
            "symbol": "XIN9",  # 示例占位，实际以 A50 期指代码为准
            "name": "富时中国 A50 指数期货",
            "daily": True,
            "minute": True,
            "tick": False,
            "realtime": False,
        },
        "options_510300": {
            "underlying": "510300",
            "supports_chain": True,
            "supports_iv": False,
            "supports_greeks": False,
            "notes": [
                "已根据 2026-01-16 上交所公告预留 510300 期权支持位，"
                "实际 IV / Greeks 能力取决于对接的数据源。",
            ],
        },
    }


def _load_yaml_config(path: str) -> Dict[str, Any]:
    """轻量封装 YAML 读取，YAML 库缺失或文件不存在时返回空配置。"""
    try:
        import yaml  # type: ignore[import]
    except Exception:
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _merge_tick_capabilities(data_feeds: Dict[str, Any]) -> None:
    """
    根据 etf-options-ai-assistant 根目录下 config.yaml 中的 data_sources.tick 段更新 Tick 能力标记。

    仅负责把“已正确配置且启用的 Tick 源”反映到 data_feeds 中，
    具体的探测成功/失败由数据采集层负责。
    """
    config_path = "/home/xie/etf-options-ai-assistant/config.yaml"
    cfg = _load_yaml_config(config_path)
    data_sources = cfg.get("data_sources") or {}
    tick_cfg = data_sources.get("tick") or {}
    providers = tick_cfg.get("providers") or {}
    symbols = tick_cfg.get("symbols") or {}

    itick_enabled = bool(providers.get("itick", {}).get("enabled"))
    alltick_enabled = bool(providers.get("allticks", {}).get("enabled") or providers.get("alltick", {}).get("enabled"))

    has_any_tick_provider = itick_enabled or alltick_enabled

    def mark_tick(symbol_key: str, feed_key: str) -> None:
        if not has_any_tick_provider:
            return
        if symbol_key not in symbols:
            return
        feed = data_feeds.get(feed_key)
        if not isinstance(feed, dict):
            return
        feed["tick"] = True

    mark_tick("000300", "index_000300")
    mark_tick("399006", "index_399006")


def get_runtime_environment_view() -> Dict[str, Any]:
    """
    返回当前运行环境的统一视图，供 `option_trader.py env` 使用。

    当前实现：
    - 使用本地静态配置（默认是保守配置）；
    - 可以在此函数中加入探测逻辑，例如：
      - 根据已安装的 iTick / Tushare / AKShare 等模块动态补充说明；
      - 根据环境变量标记是否允许真实下单等。
    """
    broker = _default_broker_config()
    data_feeds = _default_data_feeds()
    _merge_tick_capabilities(data_feeds)

    return {
        "broker": broker,
        "data_feeds": data_feeds,
        "assumptions": [
            "当前环境视图基于本地静态配置、config.yaml 以及保守假设。",
            "如有实盘与期权权限，请在 `broker_and_data_config.py` 与 config.yaml 中补充真实信息。",
        ],
    }


__all__ = ["get_runtime_environment_view"]

