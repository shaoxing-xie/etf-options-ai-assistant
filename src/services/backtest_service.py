from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.services.market_data_service import MarketDataService


@dataclass
class BacktestConfig:
    symbol: str
    lookback_days: int = 240
    fast_ma: int = 10
    slow_ma: int = 30
    fee_bps: float = 3.0
    slippage_bps: float = 2.0
    capital: float = 1.0


class BacktestService:
    """Lightweight crossover backtest for chart research."""

    def __init__(self) -> None:
        self.market = MarketDataService()

    def run_ma_crossover(self, cfg: BacktestConfig) -> dict[str, Any]:
        if cfg.fast_ma >= cfg.slow_ma:
            return {"success": False, "message": "fast_ma must be less than slow_ma", "data": None}
        ohlcv = self.market.get_ohlcv(symbol=cfg.symbol, lookback_days=cfg.lookback_days)
        if not ohlcv.get("success"):
            return {"success": False, "message": ohlcv.get("message", "load data failed"), "data": None}
        df = ohlcv.get("data")
        if df is None or df.empty:
            return {"success": False, "message": "no data", "data": None}

        bt = df.copy()
        bt["fast_ma"] = bt["close"].rolling(cfg.fast_ma).mean()
        bt["slow_ma"] = bt["close"].rolling(cfg.slow_ma).mean()
        bt = bt.dropna(subset=["fast_ma", "slow_ma"]).copy()
        if bt.empty:
            return {"success": False, "message": "insufficient data after MA warmup", "data": None}

        bt["signal"] = (bt["fast_ma"] > bt["slow_ma"]).astype(int)
        bt["pos"] = bt["signal"].shift(1).fillna(0)
        bt["ret"] = bt["close"].pct_change().fillna(0.0)
        bt["turnover"] = bt["signal"].diff().fillna(0).abs()
        cost_per_trade = (float(cfg.fee_bps) + float(cfg.slippage_bps)) / 10000.0
        bt["trade_cost"] = bt["turnover"] * cost_per_trade
        bt["strategy_ret_raw"] = bt["ret"] * bt["pos"]
        bt["strategy_ret"] = bt["strategy_ret_raw"] - bt["trade_cost"]
        bt["equity"] = (1 + bt["strategy_ret"]).cumprod()
        bt["benchmark"] = (1 + bt["ret"]).cumprod()
        bt["trade_flag"] = bt["turnover"]
        bt["capital_curve"] = bt["equity"] * float(cfg.capital)

        total_return = float(bt["equity"].iloc[-1] - 1.0)
        benchmark_return = float(bt["benchmark"].iloc[-1] - 1.0)
        running_max = bt["equity"].cummax()
        drawdown = (bt["equity"] / running_max - 1.0).min()
        trades = int(bt["trade_flag"].sum())
        win_rate = float((bt["strategy_ret"] > 0).mean())
        cost_total = float(bt["trade_cost"].sum())
        sharpe = 0.0
        std = float(bt["strategy_ret"].std())
        if std > 0:
            sharpe = float(bt["strategy_ret"].mean() / std * (252**0.5))

        return {
            "success": True,
            "message": "ok",
            "data": {
                "series": bt,
                "metrics": {
                    "total_return": round(total_return, 4),
                    "benchmark_return": round(benchmark_return, 4),
                    "max_drawdown": round(float(drawdown), 4),
                    "trade_count": trades,
                    "win_rate": round(win_rate, 4),
                    "total_cost": round(cost_total, 6),
                    "sharpe": round(sharpe, 4),
                },
                "cache_status": ohlcv.get("cache_status", {}),
                "config": {
                    "fast_ma": cfg.fast_ma,
                    "slow_ma": cfg.slow_ma,
                    "fee_bps": cfg.fee_bps,
                    "slippage_bps": cfg.slippage_bps,
                    "capital": cfg.capital,
                },
            },
        }
