"""
期权交易信号入口：按配置解析标的与关联指数，拉取数据并调用 signal_generator.generate_signals。
对外工具名：tool_generate_option_trading_signals；tool_generate_signals 为兼容别名。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.config_loader import load_system_config
from src.data_collector import (
    fetch_index_minute_data_with_fallback,
    get_etf_current_price,
)
from src.data_storage import load_trend_analysis
from src.logger_config import get_module_logger
from src.signal_generator import generate_signals
from src.signal_universe import ResolvedOptionTarget, resolve_option_target

logger = get_module_logger(__name__)


def _option_meta(underlying: str, index_symbol: str, data_quality: str = "ok", skip_reason: Optional[str] = None) -> Dict[str, Any]:
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "option_signal_engine",
        "data_quality": data_quality,
        "skip_reason": skip_reason,
        "index_symbol": index_symbol,
    }


def _attach_option_envelope(data: Dict[str, Any], underlying: str, index_symbol: str) -> Dict[str, Any]:
    out = dict(data)
    out["asset_class"] = "option"
    out["symbol"] = underlying
    out["meta"] = _option_meta(underlying, index_symbol)
    return out


def _try_opening_strategy(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not config:
        return None
    for analysis_type in ("opening_market", "before_open"):
        try:
            raw = load_trend_analysis(analysis_type=analysis_type, config=config)
            if isinstance(raw, dict) and raw.get("final_trend") is not None:
                return raw
        except Exception as e:
            logger.debug("加载开盘策略失败 %s: %s", analysis_type, e)
    return None


def _build_volatility_and_contracts(
    resolved: ResolvedOptionTarget,
    config: Optional[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    row = resolved.row
    max_n = max(1, resolved.max_contracts_per_side)
    call_ranges: List[Dict[str, Any]] = []
    put_ranges: List[Dict[str, Any]] = []
    for c in (row.get("call_contracts") or [])[:max_n]:
        if not isinstance(c, dict):
            continue
        cc = c.get("contract_code")
        if cc is None:
            continue
        call_ranges.append(
            {
                "contract_code": str(cc),
                "strike_price": c.get("strike_price"),
                "name": str(cc),
                "current_price": c.get("current_price"),
            }
        )
    for p in (row.get("put_contracts") or [])[:max_n]:
        if not isinstance(p, dict):
            continue
        pc = p.get("contract_code")
        if pc is None:
            continue
        put_ranges.append(
            {
                "contract_code": str(pc),
                "strike_price": p.get("strike_price"),
                "name": str(pc),
                "current_price": p.get("current_price"),
            }
        )

    volatility_ranges: Optional[Dict[str, Any]] = None
    if config is not None:
        try:
            from src.on_demand_predictor import predict_etf_volatility_range_on_demand

            pred = predict_etf_volatility_range_on_demand(symbol=resolved.underlying, config=config)
            if pred.get("success"):
                volatility_ranges = {
                    "etf_range": {
                        "upper": float(pred.get("upper", 0) or 0),
                        "lower": float(pred.get("lower", 0) or 0),
                        "current_price": float(pred.get("current_price", 0) or 0),
                        "confidence": float(pred.get("confidence", 0.5) or 0.5),
                    },
                    "call_ranges": call_ranges,
                    "put_ranges": put_ranges,
                }
        except Exception as e:
            logger.debug("即时波动区间预测跳过: %s", e)

    if volatility_ranges is None:
        volatility_ranges = {
            "etf_range": None,
            "call_ranges": call_ranges,
            "put_ranges": put_ranges,
        }
    else:
        volatility_ranges["call_ranges"] = call_ranges
        volatility_ranges["put_ranges"] = put_ranges

    return volatility_ranges, call_ranges, put_ranges


def _load_side_greeks(
    ranges: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]],
) -> Optional[pd.DataFrame]:
    if not ranges or not config:
        return None
    code = ranges[0].get("contract_code")
    if not code:
        return None
    try:
        from src.data_cache import get_cached_option_greeks

        date_s = datetime.now().strftime("%Y%m%d")
        df = get_cached_option_greeks(str(code), date_s, config=config)
        if df is None or df.empty:
            return None
        if "contract_code" not in df.columns:
            df = df.copy()
            df["contract_code"] = str(code)
        return df
    except Exception as e:
        logger.debug("读取期权 Greeks 缓存失败 %s: %s", code, e)
        return None


def tool_generate_option_trading_signals(
    underlying: str = "510300",
    mode: str = "production",
) -> Dict[str, Any]:
    """
    根据配置与标的生成期权交易信号（使用关联指数分钟线 + 可选波动区间 / 合约骨架 / Greeks / 开盘策略）。
    """
    try:
        config: Optional[Dict[str, Any]] = None
        try:
            config = load_system_config()
        except Exception as e:
            logger.debug("加载系统配置失败: %s", e, exc_info=True)

        resolved = resolve_option_target(config or {}, underlying=underlying if underlying else None)
        if not resolved.enabled:
            return {
                "success": False,
                "message": f"标的 {resolved.underlying} 在配置中已禁用",
                "data": None,
            }

        u = resolved.underlying
        index_symbol = resolved.index_symbol

        index_30m, _index_15m = fetch_index_minute_data_with_fallback(
            lookback_days=5,
            max_retries=2,
            retry_delay=1.0,
            symbol=index_symbol,
        )
        if index_30m is None or index_30m.empty:
            return {
                "success": False,
                "message": f"获取指数 {index_symbol} 分钟数据失败或为空，无法生成信号",
                "data": None,
            }

        etf_price = get_etf_current_price(symbol=u)
        if etf_price is None or etf_price <= 0:
            return {
                "success": False,
                "message": f"获取ETF {u} 当前价失败或无效，无法生成信号",
                "data": None,
            }

        volatility_ranges, call_ranges, put_ranges = _build_volatility_and_contracts(resolved, config)
        call_greeks = _load_side_greeks(call_ranges, config)
        put_greeks = _load_side_greeks(put_ranges, config)
        opening_strategy = _try_opening_strategy(config)

        signals = generate_signals(
            index_minute=index_30m,
            etf_current_price=float(etf_price),
            config=config,
            volatility_ranges=volatility_ranges,
            call_option_greeks=call_greeks,
            put_option_greeks=put_greeks,
            opening_strategy=opening_strategy,
        )

        if not signals or not isinstance(signals, list):
            empty = {
                "signal_id": datetime.now().strftime("%Y%m%d%H%M%S"),
                "signal_type": None,
                "signal_strength": None,
                "trend_strength": None,
                "signal_confidence": None,
                "signals": [],
            }
            return {
                "success": True,
                "message": "当前无新信号（去重或条件未触发）",
                "data": _attach_option_envelope(empty, u, index_symbol),
            }

        strengths: List[float] = []
        for s in signals:
            if not isinstance(s, dict):
                continue
            v = s.get("signal_strength", None)
            try:
                if v is not None:
                    strengths.append(float(v))
            except (TypeError, ValueError):
                continue

        max_strength = max(strengths) if strengths else None
        max_signal = None
        if max_strength is not None:
            for s in signals:
                if isinstance(s, dict) and s.get("signal_strength", None) == max_strength:
                    max_signal = s
                    break
        rep = max_signal if isinstance(max_signal, dict) else signals[0]

        signal_types = sorted(
            set(str(s.get("signal_type")) for s in signals if isinstance(s, dict) and s.get("signal_type"))
        )
        if len(signal_types) >= 2:
            signal_type_out = "both"
        else:
            signal_type_out = signal_types[0] if signal_types else None

        first = rep
        signal_id = (
            str(first.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            .replace("-", "")
            .replace(":", "")
            .replace(" ", "")[:14]
        )
        payload = {
            "signal_id": signal_id,
            "signal_type": signal_type_out,
            "signal_strength": max_strength if max_strength is not None else first.get("signal_strength"),
            "trend_strength": first.get("trend_strength", first.get("signal_strength")),
            "signal_confidence": first.get(
                "signal_confidence",
                max_strength if max_strength is not None else first.get("signal_strength"),
            ),
            "signals": signals,
        }
        return {
            "success": True,
            "message": f"已生成 {len(signals)} 个信号",
            "data": _attach_option_envelope(payload, u, index_symbol),
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"信号生成执行异常：{str(e)}",
            "data": None,
        }


def tool_generate_signals(
    underlying: str = "510300",
    mode: str = "production",
) -> Dict[str, Any]:
    """兼容别名，等同于 tool_generate_option_trading_signals。"""
    return tool_generate_option_trading_signals(underlying=underlying, mode=mode)
