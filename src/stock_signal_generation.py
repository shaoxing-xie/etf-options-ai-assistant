"""
A 股交易信号工具：日线趋势 + 30 分钟 RSI + 成交量确认（可配置阈值）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import pytz

from src.config_loader import load_system_config
from src.data_collector import (
    fetch_stock_daily_hist,
    fetch_stock_minute_data_with_fallback,
    get_stock_current_price,
)
from src.indicator_calculator import calculate_rsi
from src.logger_config import get_module_logger
from src.signal_universe import resolve_stock_target

logger = get_module_logger(__name__)


def _daily_close_col(df: pd.DataFrame) -> str:
    if "收盘" in df.columns:
        return "收盘"
    if "close" in df.columns:
        return "close"
    raise ValueError("日线数据缺少收盘列")


def _stock_envelope(
    symbol: str,
    signals: List[Dict[str, Any]],
    data_quality: str = "ok",
    skip_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "asset_class": "stock",
        "symbol": symbol,
        "signals": signals,
        "meta": {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "stock_rule_v0",
            "data_quality": data_quality,
            "skip_reason": skip_reason,
        },
    }


def _evaluate_stock_rules(
    symbol: str,
    daily: pd.DataFrame,
    minute_30m: Optional[pd.DataFrame],
    spot: float,
    st: Dict[str, Any],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    close_col = _daily_close_col(daily)
    rsi_os = float(st.get("rsi_oversold", 35))
    rsi_ob = float(st.get("rsi_overbought", 65))
    vol_mult = float(st.get("volume_vs_ma5_mult", 1.35))
    min_str = float(st.get("min_strength", 0.45))

    closes = pd.to_numeric(daily[close_col], errors="coerce")
    if closes.isna().all() or len(closes) < 25:
        return out

    ma20 = closes.rolling(20).mean().iloc[-1]
    last_close = float(closes.iloc[-1])
    vol_col = "成交量" if "成交量" in daily.columns else ("volume" if "volume" in daily.columns else None)
    if vol_col and len(daily) >= 6:
        vols = pd.to_numeric(daily[vol_col], errors="coerce")
        vol_ma5 = vols.rolling(5).mean().iloc[-1]
        last_vol = float(vols.iloc[-1])
        vol_ok = vol_ma5 > 0 and last_vol >= vol_ma5 * vol_mult
    else:
        vol_ok = False

    daily_bull = last_close > float(ma20)
    daily_bear = last_close < float(ma20)

    # 涨跌停粗判：极端涨跌日不生成方向信号
    try:
        if len(daily) >= 2:
            prev_c = float(closes.iloc[-2])
            day_chg = (last_close - prev_c) / prev_c * 100.0 if prev_c else 0.0
            if day_chg >= 9.5 or day_chg <= -9.5:
                logger.info("股票 %s 日内涨跌 %.1f%%，跳过方向信号", symbol, day_chg)
                return out
    except Exception:
        pass

    m_rsi = None
    if minute_30m is not None and not minute_30m.empty and "收盘" in minute_30m.columns:
        rsi_ser = calculate_rsi(minute_30m, close_col="收盘")
        if rsi_ser is not None and not rsi_ser.empty:
            m_rsi = float(rsi_ser.iloc[-1])

    if m_rsi is None:
        return out

    if daily_bull and m_rsi < rsi_os and vol_ok:
        strength = min(0.85, min_str + (rsi_os - m_rsi) / 100.0)
        out.append(
            {
                "signal_type": "bullish_pullback",
                "direction": "偏多",
                "signal_strength": round(strength, 3),
                "reason": f"日线位于MA20上方，30m RSI={m_rsi:.1f} 超卖区，成交量≥5日均量×{vol_mult}",
                "symbol": symbol,
                "spot_price": spot,
                "daily_ma20": round(float(ma20), 4),
                "minute_rsi": round(m_rsi, 2),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    elif daily_bear and m_rsi > rsi_ob and vol_ok:
        strength = min(0.85, min_str + (m_rsi - rsi_ob) / 100.0)
        out.append(
            {
                "signal_type": "bearish_bounce",
                "direction": "偏空",
                "signal_strength": round(strength, 3),
                "reason": f"日线位于MA20下方，30m RSI={m_rsi:.1f} 超买区，成交量≥5日均量×{vol_mult}",
                "symbol": symbol,
                "spot_price": spot,
                "daily_ma20": round(float(ma20), 4),
                "minute_rsi": round(m_rsi, 2),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    return out


def tool_generate_stock_trading_signals(
    symbol: Optional[str] = None,
    mode: str = "production",
) -> Dict[str, Any]:
    try:
        config = load_system_config()
        target = resolve_stock_target(config, stock_symbol=symbol)
        if target is None:
            return {
                "success": False,
                "message": "A 股信号监控已关闭 (signal_generation.stock.enabled=false)",
                "data": _stock_envelope(symbol or "", [], data_quality="unavailable", skip_reason="disabled"),
            }

        sym = target.symbol
        st = (config.get("signal_params") or {}).get("stock_short_term") or {}

        spot = get_stock_current_price(sym)
        if spot is None or spot <= 0:
            return {
                "success": False,
                "message": f"无法获取股票 {sym} 现价",
                "data": _stock_envelope(sym, [], data_quality="unavailable", skip_reason="no_price"),
            }

        tz = pytz.timezone("Asia/Shanghai")
        end = datetime.now(tz).strftime("%Y%m%d")
        start = (datetime.now(tz) - timedelta(days=400)).strftime("%Y%m%d")
        daily = fetch_stock_daily_hist(sym, start, end)
        if daily is None or daily.empty:
            return {
                "success": False,
                "message": f"股票 {sym} 日线数据缺失",
                "data": _stock_envelope(sym, [], data_quality="degraded", skip_reason="no_daily"),
            }

        m30, _m15 = fetch_stock_minute_data_with_fallback(
            symbol=sym,
            lookback_days=15,
            max_retries=2,
            retry_delay=1.0,
        )

        signals = _evaluate_stock_rules(sym, daily, m30, float(spot), st)
        if not signals:
            return {
                "success": True,
                "message": "当前无 A 股规则信号（条件未同时满足）",
                "data": _stock_envelope(sym, [], skip_reason="no_trigger"),
            }
        return {
            "success": True,
            "message": f"已生成 {len(signals)} 条 A 股监控信号",
            "data": _stock_envelope(sym, signals),
        }
    except Exception as e:
        logger.exception("股票信号生成异常: %s", e)
        return {
            "success": False,
            "message": f"股票信号生成异常：{e}",
            "data": _stock_envelope(symbol or "", [], data_quality="unavailable", skip_reason=str(e)),
        }
