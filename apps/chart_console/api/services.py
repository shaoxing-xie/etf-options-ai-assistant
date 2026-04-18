from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.services.backtest_service import BacktestConfig, BacktestService
from src.services.indicator_service import IndicatorService
from src.services.market_data_service import MarketDataService
from src.services.workspace_service import WorkspaceService

ROOT = Path(__file__).resolve().parents[3]
ALERTS_PATH = ROOT / "config" / "alerts.yaml"
MARKET_DATA_PATH = ROOT / "config" / "domains" / "market_data.yaml"
ANALYTICS_PATH = ROOT / "config" / "domains" / "analytics.yaml"


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

    def get_alerts_config_text(self) -> dict[str, Any]:
        """Return raw alerts.yaml content for the config center editor."""
        if not ALERTS_PATH.exists():
            return {"success": True, "message": "ok", "data": {"path": str(ALERTS_PATH), "text": ""}}
        try:
            return {
                "success": True,
                "message": "ok",
                "data": {"path": str(ALERTS_PATH), "text": ALERTS_PATH.read_text(encoding="utf-8")},
            }
        except Exception as e:
            return {"success": False, "message": f"read alerts.yaml failed: {e}"}

    def save_alerts_config_text(self, text: str) -> dict[str, Any]:
        """Save alerts.yaml with timestamped backup for quick rollback."""
        try:
            ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            if ALERTS_PATH.exists():
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = ALERTS_PATH.with_name(f"alerts.yaml.bak.{ts}")
                try:
                    backup.write_text(ALERTS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    # Backup failure should not block saving; still try to write the new file.
                    pass
            ALERTS_PATH.write_text(text, encoding="utf-8")
            return {"success": True, "message": "ok", "data": {"path": str(ALERTS_PATH)}}
        except Exception as e:
            return {"success": False, "message": f"save alerts.yaml failed: {e}"}

    def get_market_data_config_text(self) -> dict[str, Any]:
        if not MARKET_DATA_PATH.exists():
            return {"success": True, "message": "ok", "data": {"path": str(MARKET_DATA_PATH), "text": ""}}
        try:
            return {
                "success": True,
                "message": "ok",
                "data": {"path": str(MARKET_DATA_PATH), "text": MARKET_DATA_PATH.read_text(encoding="utf-8")},
            }
        except Exception as e:
            return {"success": False, "message": f"read market_data.yaml failed: {e}"}

    def save_market_data_config_text(self, text: str) -> dict[str, Any]:
        try:
            MARKET_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
            if MARKET_DATA_PATH.exists():
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = MARKET_DATA_PATH.with_name(f"{MARKET_DATA_PATH.name}.bak.{ts}")
                try:
                    backup.write_text(MARKET_DATA_PATH.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass
            MARKET_DATA_PATH.write_text(text, encoding="utf-8")
            return {"success": True, "message": "ok", "data": {"path": str(MARKET_DATA_PATH)}}
        except Exception as e:
            return {"success": False, "message": f"save market_data.yaml failed: {e}"}

    def get_analytics_config_text(self) -> dict[str, Any]:
        if not ANALYTICS_PATH.exists():
            return {"success": True, "message": "ok", "data": {"path": str(ANALYTICS_PATH), "text": ""}}
        try:
            return {
                "success": True,
                "message": "ok",
                "data": {"path": str(ANALYTICS_PATH), "text": ANALYTICS_PATH.read_text(encoding="utf-8")},
            }
        except Exception as e:
            return {"success": False, "message": f"read analytics.yaml failed: {e}"}

    def save_analytics_config_text(self, text: str) -> dict[str, Any]:
        try:
            ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
            if ANALYTICS_PATH.exists():
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = ANALYTICS_PATH.with_name(f"{ANALYTICS_PATH.name}.bak.{ts}")
                try:
                    backup.write_text(ANALYTICS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass
            ANALYTICS_PATH.write_text(text, encoding="utf-8")
            return {"success": True, "message": "ok", "data": {"path": str(ANALYTICS_PATH)}}
        except Exception as e:
            return {"success": False, "message": f"save analytics.yaml failed: {e}"}
