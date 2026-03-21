"""
历史波动率工具。

为工作流与 merged.volatility(mode="historical") 提供统一入口：
- tool_calculate_historical_volatility
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional


def tool_calculate_historical_volatility(
    symbol: str = "510300",
    data_type: Optional[str] = None,
    lookback_days: int = 60,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    """
    计算历史波动率（年化，%）。

    Args:
        symbol: ETF 或指数代码
        data_type: etf_daily | index_daily（可选；不传则按 symbol 推断）
        lookback_days: 用于计算波动率的收益率样本长度（默认 60）
        start_date/end_date: 可选 YYYYMMDD；不传则自动取最近一段时间
    """
    try:
        from src.logger_config import get_module_logger
        from src.config_loader import load_system_config
        from src.data_collector import fetch_index_daily_em  # 会自动识别 ETF 并走 fetch_etf_daily_em
        from src.indicator_calculator import calculate_historical_volatility

        logger = get_module_logger(__name__)
        cfg = load_system_config(use_cache=True)

        sym = str(symbol)
        tz_now = datetime.now()

        if end_date:
            end_ymd = str(end_date)[:8]
        else:
            end_ymd = tz_now.strftime("%Y%m%d")

        if start_date:
            start_ymd = str(start_date)[:8]
        else:
            # 为了确保足够交易日，按日历天扩大窗口
            start_ymd = (tz_now - timedelta(days=max(int(lookback_days) * 2, 90))).strftime("%Y%m%d")

        # 拉取（内部含缓存命中/补齐并写缓存的逻辑）
        df = fetch_index_daily_em(symbol=sym, period="daily", start_date=start_ymd, end_date=end_ymd)
        if df is None or getattr(df, "empty", True):
            return {
                "success": False,
                "message": f"Failed to fetch daily data for {sym}",
                "data": None,
            }

        # 推断收盘列
        close_col = "收盘" if "收盘" in df.columns else ("close" if "close" in df.columns else None)
        if close_col is None:
            return {
                "success": False,
                "message": f"Missing close column in daily data for {sym}",
                "data": {"available_columns": list(df.columns)},
            }

        period = int(lookback_days) if int(lookback_days) > 1 else 20
        hv = calculate_historical_volatility(df, period=period, close_col=close_col, data_period="day")
        if hv is None:
            return {
                "success": False,
                "message": f"Not enough data to calculate historical volatility (period={period})",
                "data": {
                    "symbol": sym,
                    "period": period,
                    "rows": int(len(df)),
                },
            }

        logger.info("历史波动率计算成功: %s, period=%s, hv=%.2f%%", sym, period, hv)
        return {
            "success": True,
            "message": "Historical volatility calculated",
            "data": {
                "symbol": sym,
                "data_type": data_type,
                "lookback_days": period,
                "volatility": float(hv),
                "annualized_volatility": float(hv),
                "start_date": start_ymd,
                "end_date": end_ymd,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "source": "daily_data",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error calculating historical volatility: {e}",
            "data": None,
        }

