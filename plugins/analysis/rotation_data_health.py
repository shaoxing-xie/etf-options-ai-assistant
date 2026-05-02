from __future__ import annotations

import importlib
from datetime import datetime
from typing import Any, Dict, List, Tuple

from plugins.data_access.read_cache_data import read_cache_data


def _split_symbols(symbols: str) -> List[str]:
    return [s.strip() for s in str(symbols or "").split(",") if s.strip()]


def _try_fetch_daily_fallback(symbol: str, *, lookback_days: int) -> Tuple[bool, str]:
    """
    Best-effort fallback check: try loading an ETF daily series from existing collectors.
    This is used only for readiness diagnostics (no persistence here).
    """
    try:
        mod = importlib.import_module("plugins.data_collection.etf.fetch_historical")
        fetcher = getattr(mod, "fetch_single_etf_historical", None)
        if fetcher is None:
            return False, "fallback_fetcher_missing"
        df, src = fetcher(etf_code=symbol, lookback_days=int(lookback_days or 60))  # type: ignore[misc]
        ok = df is not None and (len(df) if hasattr(df, "__len__") else 0) >= 3
        return bool(ok), str(src or "unknown")
    except Exception:
        return False, "fallback_fetch_exception"


def tool_rotation_data_health_check(symbols: str, lookback_days: int = 120) -> Dict[str, Any]:
    """
    Rotation readiness health check (assistant-side).

    - Reads local cache via data_access.read_cache_data.read_cache_data
    - If cache misses, performs a lightweight fallback fetch probe
    - Returns an additive, JSON-serializable diagnostic payload
    """
    syms = _split_symbols(symbols)
    if not syms:
        return {"success": False, "message": "symbols_empty", "data": {"records": []}}

    records: List[Dict[str, Any]] = []
    degraded_evidence: List[Dict[str, Any]] = []
    cache_ok = 0
    cache_total = 0
    for sym in syms:
        cache_total += 1
        cache = read_cache_data(data_type="etf_daily", symbol=sym, lookback_days=int(lookback_days or 120), return_df=False)
        hit = bool(isinstance(cache, dict) and cache.get("success") and cache.get("df") is not None)
        if hit:
            cache_ok += 1
        fallback_ok, fallback_src = (False, "")
        retry_attempts = 0
        if not hit:
            retry_attempts = 1
            fallback_ok, fallback_src = _try_fetch_daily_fallback(sym, lookback_days=int(lookback_days or 120))
            degraded_evidence.append(
                {
                    "symbol": sym,
                    "reason": "cache_miss",
                    "missing_dates": (cache or {}).get("missing_dates") if isinstance(cache, dict) else [],
                    "retry_attempts": retry_attempts,
                    "fallback_ok": fallback_ok,
                    "fallback_source": fallback_src,
                }
            )

        records.append(
            {
                "symbol": sym,
                "cache_hit": hit,
                "fallback_ok": fallback_ok,
                "fallback_source": fallback_src,
            }
        )

    coverage = (cache_ok / cache_total) if cache_total else 0.0
    # Keep legacy keys for consumers/tests (industry/concept are placeholders for now).
    return {
        "success": True,
        "message": "ok",
        "data": {
            "trade_date": datetime.now().strftime("%Y-%m-%d"),
            "lookback_days": int(lookback_days or 120),
            "industry_coverage": coverage,
            "concept_coverage": coverage,
            "records": records,
            "degraded_evidence": degraded_evidence,
        },
    }

