from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import pytz

from plugins.data_access.read_cache_data import read_cache_data
from plugins.data_collection.etf.fetch_historical import tool_fetch_etf_historical
from plugins.merged.fetch_etf_data import tool_fetch_etf_data


@dataclass
class CacheStatus:
    source: str
    success: bool
    message: str
    missing_dates: list[str]
    record_count: int


def _today_shanghai() -> datetime:
    tz = pytz.timezone("Asia/Shanghai")
    return datetime.now(tz)


class MarketDataService:
    """Unified market data facade for charting and alerting."""
    def __init__(self) -> None:
        self.root = Path(__file__).resolve().parents[2]

    def get_ohlcv(
        self,
        symbol: str,
        data_type: str = "etf_daily",
        period: Optional[str] = None,
        lookback_days: int = 180,
    ) -> Dict[str, Any]:
        # Try current date first, then roll back a few days.
        payload, rolled_days = self._read_with_recent_fallback(
            symbol=symbol,
            data_type=data_type,
            period=period,
            lookback_days=lookback_days,
            max_rollback_days=7,
        )
        df = payload.get("df")
        if df is None:
            fetch_source = ""
            # Prefer local CSV fallback first to avoid repeated network pulls in Streamlit reruns.
            fetched = self._load_local_daily_csv(symbol=symbol, lookback_days=lookback_days)
            if fetched is not None and not fetched.empty:
                fetch_source = "local_csv"
            if fetched is None or fetched.empty:
                # Prefer dedicated data_collection ETF historical tool for richer OHLC fields.
                fetched = self._fetch_historical_etf_data_collection(symbol=symbol, lookback_days=lookback_days)
                if fetched is not None and not fetched.empty:
                    fetch_source = "data_collection_historical"
            if fetched is None or fetched.empty:
                # Cache fallback: pull historical data from provider for chart display.
                fetched = self._fetch_historical_etf(symbol=symbol, lookback_days=lookback_days)
                if fetched is not None and not fetched.empty:
                    fetch_source = "merged_historical"
            if fetched is None or fetched.empty:
                return {
                    "success": False,
                    "message": payload.get("message", "cache read failed"),
                    "data": None,
                    "cache_status": self._cache_status(payload, 0),
                }
            normalized = self._normalize_ohlcv(fetched)
            return {
                "success": True,
                "message": f"cache miss -> fetched from {fetch_source or 'historical_fallback'}",
                "data": normalized,
                "cache_status": {
                    "source": fetch_source or "historical_fetch_fallback",
                    "success": True,
                    "message": f"fetched from {fetch_source or 'historical provider'}",
                    "missing_dates": payload.get("missing_dates") or [],
                    "record_count": len(normalized),
                    "rolled_back_days": rolled_days,
                },
            }

        normalized = self._normalize_ohlcv(df)
        normalized_source = "cache"
        if not self._has_required_ohlc(normalized):
            # Cache may contain close-only data; enrich using collection plugin historical fetch.
            enriched = self._fetch_historical_etf_data_collection(symbol=symbol, lookback_days=lookback_days)
            if enriched is not None and not enriched.empty:
                normalized = self._normalize_ohlcv(enriched)
                normalized_source = "cache+data_collection_historical"
        cache_status = self._cache_status(payload, len(normalized))
        cache_status["source"] = normalized_source
        if rolled_days > 0:
            cache_status["rolled_back_days"] = rolled_days
            cache_status["message"] = f"{cache_status.get('message','')} (rolled back {rolled_days} day(s))".strip()
        return {
            "success": True,
            "message": payload.get("message", "ok"),
            "data": normalized,
            "cache_status": cache_status,
        }

    def _fetch_historical_etf(self, symbol: str, lookback_days: int) -> pd.DataFrame | None:
        now = _today_shanghai()
        end_date = now.strftime("%Y%m%d")
        start_date = (now - timedelta(days=lookback_days)).strftime("%Y%m%d")
        resp = tool_fetch_etf_data(
            data_type="historical",
            etf_code=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
        )
        if not isinstance(resp, dict) or not resp.get("success"):
            return None
        data = resp.get("data")
        rows = None
        if isinstance(data, dict):
            rows = data.get("klines") if isinstance(data.get("klines"), list) else data.get("records")
        elif isinstance(data, list):
            rows = data
        if not isinstance(rows, list) or not rows:
            return None
        try:
            return pd.DataFrame(rows)
        except Exception:
            return None

    def _fetch_historical_etf_data_collection(self, symbol: str, lookback_days: int) -> pd.DataFrame | None:
        now = _today_shanghai()
        end_date = now.strftime("%Y%m%d")
        start_date = (now - timedelta(days=lookback_days)).strftime("%Y%m%d")
        try:
            resp = tool_fetch_etf_historical(
                etf_code=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                use_cache=True,
            )
        except Exception:
            return None
        if not isinstance(resp, dict) or not resp.get("success"):
            return None
        data = resp.get("data")
        if isinstance(data, dict):
            rows = data.get("klines")
            if isinstance(rows, list) and rows:
                try:
                    return pd.DataFrame(rows)
                except Exception:
                    return None
        return None

    def _load_local_daily_csv(self, symbol: str, lookback_days: int) -> pd.DataFrame | None:
        csv_path = self.root / "data" / "etf_daily" / f"{symbol}.csv"
        if not csv_path.is_file():
            return None
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            return None
        if df.empty:
            return None
        dt_col = None
        for c in ("日期", "date", "datetime", "time"):
            if c in df.columns:
                dt_col = c
                break
        if dt_col:
            df[dt_col] = pd.to_datetime(df[dt_col], errors="coerce")
            df = df.dropna(subset=[dt_col]).sort_values(dt_col)
            if lookback_days > 0:
                cutoff = _today_shanghai().replace(tzinfo=None) - timedelta(days=lookback_days)
                df = df[df[dt_col] >= cutoff]
        return df.reset_index(drop=True)

    def _read_with_recent_fallback(
        self,
        symbol: str,
        data_type: str,
        period: Optional[str],
        lookback_days: int,
        max_rollback_days: int,
    ) -> tuple[Dict[str, Any], int]:
        now = _today_shanghai()
        last_payload: Dict[str, Any] = {
            "success": False,
            "message": "cache read failed",
            "df": None,
            "missing_dates": [],
        }
        for rollback in range(0, max_rollback_days + 1):
            end_dt = now - timedelta(days=rollback)
            start_dt = end_dt - timedelta(days=lookback_days)
            payload = read_cache_data(
                data_type=data_type,
                symbol=symbol,
                period=period,
                start_date=start_dt.strftime("%Y%m%d"),
                end_date=end_dt.strftime("%Y%m%d"),
                return_df=True,
            )
            df = payload.get("df")
            if df is not None and len(df) > 0:
                return payload, rollback
            last_payload = payload
        return last_payload, max_rollback_days

    def _cache_status(self, payload: Dict[str, Any], count: int) -> Dict[str, Any]:
        status = CacheStatus(
            source="cache",
            success=bool(payload.get("success")),
            message=str(payload.get("message", "")),
            missing_dates=[str(x) for x in (payload.get("missing_dates") or [])],
            record_count=count,
        )
        return {
            "source": status.source,
            "success": status.success,
            "message": status.message,
            "missing_dates": status.missing_dates,
            "record_count": status.record_count,
        }

    def _normalize_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        # Normalize common column variants from cache / tushare / local CSV exports.
        renames = {
            "日期": "datetime",
            "date": "datetime",
            "time": "datetime",
            "datetime": "datetime",
            "trade_date": "datetime",
            "timestamp": "datetime",
            "开盘": "open",
            "Open": "open",
            "OPEN": "open",
            "收盘": "close",
            "Close": "close",
            "CLOSE": "close",
            "最高": "high",
            "High": "high",
            "HIGH": "high",
            "最低": "low",
            "Low": "low",
            "LOW": "low",
            "成交量": "volume",
            "vol": "volume",
            "Volume": "volume",
            "VOLUME": "volume",
        }
        for src, dst in renames.items():
            if src in out.columns and dst not in out.columns:
                out[dst] = out[src]

        # Secondary pass: case-insensitive fallback for unexpected key styles.
        lower_to_col = {str(c).strip().lower(): c for c in out.columns}
        fallback_alias = {
            "datetime": ["datetime", "trade_date", "date", "time", "timestamp"],
            "open": ["open", "o", "open_price"],
            "high": ["high", "h", "high_price"],
            "low": ["low", "l", "low_price"],
            "close": ["close", "c", "close_price"],
            "volume": ["volume", "vol", "v"],
        }
        for dst, aliases in fallback_alias.items():
            if dst in out.columns:
                continue
            for alias in aliases:
                if alias in lower_to_col:
                    out[dst] = out[lower_to_col[alias]]
                    break

        if "datetime" in out.columns:
            out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
            out = out.dropna(subset=["datetime"]).sort_values("datetime")

        for col in ("open", "high", "low", "close", "volume"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")

        # Some fallback sources provide close-only daily series; synthesize OHLC
        # so chart rendering remains available instead of crashing.
        if "close" in out.columns:
            for col in ("open", "high", "low"):
                if col not in out.columns:
                    out[col] = out["close"]

        return out.reset_index(drop=True)

    def _has_required_ohlc(self, df: pd.DataFrame) -> bool:
        required = {"datetime", "open", "high", "low", "close"}
        return required.issubset(set(df.columns))

