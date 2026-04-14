from __future__ import annotations

from typing import Any, Dict, List, Optional

from plugins.analysis.technical_indicators import tool_calculate_technical_indicators


class IndicatorService:
    """Facade around technical indicator plugin for chart and alert features."""

    def calculate(
        self,
        symbol: str,
        data_type: str = "etf_daily",
        indicators: Optional[List[str]] = None,
        lookback_days: int = 180,
        timeframe_minutes: Optional[int] = None,
        ma_periods: Optional[List[int]] = None,
        rsi_length: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload = tool_calculate_technical_indicators(
            symbol=symbol,
            data_type=data_type,
            indicators=indicators or ["ma", "macd", "rsi", "bollinger"],
            lookback_days=lookback_days,
            timeframe_minutes=timeframe_minutes,
            ma_periods=ma_periods,
            rsi_length=rsi_length,
        )
        if not payload.get("success"):
            # Fallback: reuse chart data service multi-source fetch path instead of
            # failing hard on cache miss in technical_indicators plugin.
            try:
                from src.services.market_data_service import MarketDataService

                market = MarketDataService()
                ohlcv = market.get_ohlcv(
                    symbol=symbol,
                    data_type=data_type,
                    lookback_days=lookback_days,
                )
                df = ohlcv.get("data")
                if ohlcv.get("success") and df is not None and not df.empty:
                    payload = tool_calculate_technical_indicators(
                        symbol=symbol,
                        data_type=data_type,
                        indicators=indicators or ["ma", "macd", "rsi", "bollinger"],
                        lookback_days=lookback_days,
                        timeframe_minutes=timeframe_minutes,
                        ma_periods=ma_periods,
                        rsi_length=rsi_length,
                        klines_data=df.to_dict("records"),
                    )
            except Exception:
                # Keep original error payload if fallback path fails.
                pass
        if not payload.get("success"):
            return {"success": False, "message": payload.get("message", "indicator failed"), "data": None}
        return {
            "success": True,
            "message": payload.get("message", "ok"),
            "data": payload.get("data") or {},
        }

