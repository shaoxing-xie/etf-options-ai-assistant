from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.services.backtest_service import BacktestConfig, BacktestService
from src.services.indicator_service import IndicatorService
from src.services.market_data_service import MarketDataService
from src.services.workspace_service import WorkspaceService

ROOT = Path(__file__).resolve().parents[3]


class ApiServices:
    def __init__(self) -> None:
        self.market = MarketDataService()
        self.indicator = IndicatorService()
        self.backtest = BacktestService()
        self.workspace = WorkspaceService()
        self._cache: dict[str, tuple[float, Any]] = {}

    def cache_get(self, key: str, ttl_sec: int) -> Any | None:
        hit = self._cache.get(key)
        if not hit:
            return None
        ts, value = hit
        if time.time() - ts > ttl_sec:
            return None
        return value

    def cache_set(self, key: str, value: Any) -> Any:
        self._cache[key] = (time.time(), value)
        return value

    def get_ohlcv(self, symbol: str, lookback_days: int) -> dict[str, Any]:
        key = f"ohlcv:{symbol}:{lookback_days}"
        cached = self.cache_get(key, 15)
        if cached is not None:
            return cached
        out = self.market.get_ohlcv(symbol=symbol, lookback_days=lookback_days)
        return self.cache_set(key, out)

    def get_indicators(self, symbol: str, lookback_days: int, timeframe_minutes: int | None, ma_periods: list[int]) -> dict[str, Any]:
        key = f"ind:{symbol}:{lookback_days}:{timeframe_minutes}:{','.join(str(x) for x in ma_periods)}"
        cached = self.cache_get(key, 10)
        if cached is not None:
            return cached
        out = self.indicator.calculate(
            symbol=symbol,
            lookback_days=lookback_days,
            timeframe_minutes=timeframe_minutes,
            ma_periods=ma_periods,
        )
        return self.cache_set(key, out)

    def get_backtest(self, symbol: str, lookback_days: int, fast_ma: int, slow_ma: int, fee_bps: float, slippage_bps: float) -> dict[str, Any]:
        cfg = BacktestConfig(
            symbol=symbol,
            lookback_days=lookback_days,
            fast_ma=fast_ma,
            slow_ma=slow_ma,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        return self.backtest.run_ma_crossover(cfg)

    def get_alert_replay(self) -> dict[str, Any]:
        events_path = ROOT / "data" / "alerts" / "internal_alert_events.jsonl"
        rows: list[dict[str, Any]] = []
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        obj.setdefault("diagnostics", {})
                        obj["diagnostics"]["is_dedup"] = obj.get("status") == "dedup_skipped"
                        obj["diagnostics"]["is_cooldown"] = obj.get("status") == "cooldown_skipped"
                        rows.append(obj)
                except Exception:
                    continue
        return {"success": True, "message": "ok", "data": rows[-1000:]}
