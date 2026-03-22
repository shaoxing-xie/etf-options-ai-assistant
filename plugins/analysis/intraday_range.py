"""
日内区间预测工具（轻量版）。

该模块用于补齐工作流依赖：tool_predict_intraday_range。
实现采用 src.volatility_range_fallback 的日线降级方案，保证在多数环境可运行。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional


def tool_predict_intraday_range(
    symbol: str = "510300",
    underlying: Optional[str] = None,
    lookback_days: int = 60,
    **_: Any,
) -> Dict[str, Any]:
    """
    预测标的（ETF）当日剩余时间的价格区间。

    Args:
        symbol: ETF 代码（默认 510300）
        underlying: 兼容参数，优先于 symbol
        lookback_days: 用于获取日线窗口（默认 60）
    """
    sym = str(underlying or symbol or "510300")
    try:
        from src.config_loader import load_system_config
        from src.data_collector import fetch_etf_daily_em
        from src.volatility_range import get_remaining_trading_time
        from src.volatility_range_fallback import calculate_etf_volatility_range_fallback
        from src.logger_config import get_module_logger

        logger = get_module_logger(__name__)
        cfg = load_system_config(use_cache=True)

        # 1) 获取当前价格（优先用插件实时工具；失败则用日线最后收盘兜底）
        current_price: Optional[float] = None
        try:
            from plugins.data_collection.etf.fetch_realtime import tool_fetch_etf_realtime

            rt = tool_fetch_etf_realtime(etf_code=sym, mode="test")
            if isinstance(rt, dict) and rt.get("success"):
                d = rt.get("data", {})
                if isinstance(d, dict) and "current_price" in d:
                    current_price = float(d.get("current_price"))
                elif isinstance(d, dict) and "etf_data" in d and d["etf_data"]:
                    current_price = float(d["etf_data"][0].get("current_price"))
        except Exception:
            current_price = None

        # 2) 获取日线数据（内部含缓存逻辑）
        now = datetime.now()
        end_ymd = now.strftime("%Y%m%d")
        start_ymd = (now - timedelta(days=max(int(lookback_days) * 2, 90))).strftime("%Y%m%d")
        daily_df = fetch_etf_daily_em(symbol=sym, period="daily", start_date=start_ymd, end_date=end_ymd)
        if daily_df is None or getattr(daily_df, "empty", True):
            return {"success": False, "message": f"Failed to fetch daily data for {sym}", "data": None}

        if current_price is None:
            # 尝试用最后收盘价兜底
            close_col = "收盘" if "收盘" in daily_df.columns else ("close" if "close" in daily_df.columns else None)
            if close_col:
                try:
                    current_price = float(daily_df[close_col].iloc[-1])
                except Exception:
                    current_price = None

        if current_price is None:
            return {"success": False, "message": f"Failed to determine current price for {sym}", "data": None}

        # 3) 计算剩余交易时间与区间
        remaining_minutes = int(get_remaining_trading_time(cfg))
        rng = calculate_etf_volatility_range_fallback(
            daily_df, float(current_price), remaining_minutes, opening_strategy=None, previous_volatility_ranges=None, config=cfg
        )

        upper = float(rng.get("upper", current_price * 1.02))
        lower = float(rng.get("lower", current_price * 0.98))
        conf = float(rng.get("confidence", 0.3))

        logger.info("日内区间预测完成: %s, lower=%.4f, upper=%.4f, conf=%.2f", sym, lower, upper, conf)
        return {
            "success": True,
            "message": "Intraday range predicted",
            "data": {
                "symbol": sym,
                "current_price": float(current_price),
                "lower_bound": lower,
                "upper_bound": upper,
                "predicted_range": f"{lower:.4f} ~ {upper:.4f}",
                "confidence": conf,
                "remaining_minutes": remaining_minutes,
                "method": rng.get("method", "fallback_daily"),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "source": "fallback_daily",
        }
    except Exception as e:
        return {"success": False, "message": f"Error predicting intraday range: {e}", "data": None}

