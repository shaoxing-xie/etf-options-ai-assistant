"""
ETF 交易信号工具：基于配置 watchlist 与 generate_etf_short_term_signal。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pytz

from src.config_loader import load_system_config
from src.data_collector import (
    fetch_etf_daily_em,
    fetch_etf_minute_data_with_fallback,
    get_etf_current_price,
)
from src.etf_signal_generator_short_term import generate_etf_short_term_signal
from src.logger_config import get_module_logger
from src.signal_universe import resolve_etf_target

logger = get_module_logger(__name__)


def _etf_envelope(
    symbol: str,
    signals: list,
    index_benchmark: str,
    data_quality: str = "ok",
    skip_reason: Optional[str] = None,
    source: str = "short_term_engine",
) -> Dict[str, Any]:
    return {
        "asset_class": "etf",
        "symbol": symbol,
        "signals": signals,
        "meta": {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "data_quality": data_quality,
            "skip_reason": skip_reason,
            "index_benchmark": index_benchmark,
        },
    }


def tool_generate_etf_trading_signals(
    etf_symbol: Optional[str] = None,
    mode: str = "production",
) -> Dict[str, Any]:
    try:
        config = load_system_config()
        target = resolve_etf_target(config, etf_symbol=etf_symbol)
        if target is None:
            return {
                "success": False,
                "message": "ETF 信号监控已在配置中关闭 (signal_generation.etf.enabled=false)",
                "data": _etf_envelope(
                    etf_symbol or "",
                    [],
                    "000300",
                    data_quality="unavailable",
                    skip_reason="disabled",
                    source="etf_signal_generation",
                ),
            }

        sym = target.symbol
        bench = target.index_benchmark

        etf_price = get_etf_current_price(symbol=sym)
        if etf_price is None or etf_price <= 0:
            return {
                "success": False,
                "message": f"无法获取 ETF {sym} 现价",
                "data": _etf_envelope(sym, [], bench, data_quality="unavailable", skip_reason="no_price"),
            }

        tz_shanghai = pytz.timezone("Asia/Shanghai")
        now = datetime.now(tz_shanghai)
        end_date = now.strftime("%Y%m%d")
        start_date = (now - timedelta(days=90)).strftime("%Y%m%d")
        etf_daily = fetch_etf_daily_em(symbol=sym, start_date=start_date, end_date=end_date)
        if etf_daily is None or etf_daily.empty:
            return {
                "success": False,
                "message": f"ETF {sym} 日线数据缺失",
                "data": _etf_envelope(sym, [], bench, data_quality="degraded", skip_reason="no_daily"),
            }

        etf_minute_30m, _ = fetch_etf_minute_data_with_fallback(
            underlying=sym,
            lookback_days=15,
            max_retries=2,
            retry_delay=1.0,
        )

        sig = generate_etf_short_term_signal(
            etf_symbol=sym,
            etf_daily_data=etf_daily,
            etf_minute_30m=etf_minute_30m,
            etf_current_price=float(etf_price),
            volatility_ranges=None,
            config=config,
        )
        sig_list = [sig] if isinstance(sig, dict) else []
        if not sig_list:
            return {
                "success": True,
                "message": "当前无 ETF 短波段信号（条件未触发或未启用）",
                "data": _etf_envelope(sym, [], bench, skip_reason="no_trigger"),
            }
        return {
            "success": True,
            "message": "ETF 交易信号生成完成",
            "data": _etf_envelope(sym, sig_list, bench),
        }
    except Exception as e:
        logger.exception("ETF 信号生成异常: %s", e)
        return {
            "success": False,
            "message": f"ETF 信号生成异常：{e}",
            "data": _etf_envelope(etf_symbol or "", [], "000300", data_quality="unavailable", skip_reason=str(e)),
        }
