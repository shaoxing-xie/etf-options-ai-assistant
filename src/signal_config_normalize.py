"""
信号相关配置归一化：将 signal_generation.* 合并到运行时使用的 option_contracts / signal_params 等。
保证全库继续读取 config['option_contracts']、config['signal_params'] 即可。

合并语义（与 merge_config 一致）：**嵌套 dict 递归深合并**；**list 整键替换**
（例如 ``signal_generation.option_contracts.underlyings`` 会整体覆盖根级 ``option_contracts.underlyings``，
不会按标的逐条合并）。详见 docs/configuration/merge_semantics.md。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


def deep_merge_signal_dict(base: Optional[Dict[str, Any]], overlay: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """深度合并字典，overlay 覆盖 base 同名键；嵌套 dict 递归合并。"""
    if not base:
        base = {}
    if not overlay:
        return deepcopy(base)
    out = deepcopy(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge_signal_dict(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def _ensure_underlying_index_symbols(option_contracts: Dict[str, Any]) -> None:
    underlyings = option_contracts.get("underlyings")
    if not isinstance(underlyings, list):
        return
    for row in underlyings:
        if not isinstance(row, dict):
            continue
        if not row.get("index_symbol"):
            u = row.get("underlying", "?")
            row["index_symbol"] = "000300"
            logger.warning(
                "option_contracts.underlyings 缺少 index_symbol，已默认 000300（标的=%s）；多标的请显式配置",
                u,
            )


def normalize_signal_generation_config(config: Dict[str, Any]) -> None:
    """
    就地更新 config：应用 signal_generation 下的合约表、期权引擎参数、日内按标的、ETF/股票短参。

    - option_contracts: deep_merge(根级, signal_generation.option_contracts)，后者优先
    - signal_params: deep_merge(根级, signal_generation.option.engine)，后者优先
    - signal_params.intraday_monitor_{symbol} <- signal_generation.intraday.by_underlying[symbol]
    - etf_trading.short_term <- merge signal_generation.etf.short_term
    - signal_params.stock_short_term <- merge signal_generation.stock.short_term
    """
    sg = config.get("signal_generation")
    if not isinstance(sg, dict):
        _ensure_underlying_index_symbols(config.get("option_contracts") or {})
        return

    oc_sg = sg.get("option_contracts")
    if isinstance(oc_sg, dict) and oc_sg:
        config["option_contracts"] = deep_merge_signal_dict(config.get("option_contracts") or {}, oc_sg)

    engine = (sg.get("option") or {}).get("engine")
    if isinstance(engine, dict) and engine:
        config["signal_params"] = deep_merge_signal_dict(config.get("signal_params") or {}, engine)

    intra = sg.get("intraday") or {}
    by_u = intra.get("by_underlying") or {}
    if isinstance(by_u, dict):
        sp = config.setdefault("signal_params", {})
        for sym, block in by_u.items():
            if not isinstance(block, dict):
                continue
            key = f"intraday_monitor_{sym}"
            sp[key] = deep_merge_signal_dict(sp.get(key) or {}, block)

    etf_st = (sg.get("etf") or {}).get("short_term")
    if isinstance(etf_st, dict) and etf_st:
        etf_tr = config.setdefault("etf_trading", {})
        etf_tr["short_term"] = deep_merge_signal_dict(etf_tr.get("short_term") or {}, etf_st)

    stock_st = (sg.get("stock") or {}).get("short_term")
    if isinstance(stock_st, dict) and stock_st:
        sp = config.setdefault("signal_params", {})
        sp["stock_short_term"] = deep_merge_signal_dict(sp.get("stock_short_term") or {}, stock_st)

    _ensure_underlying_index_symbols(config.get("option_contracts") or {})
