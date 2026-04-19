#!/usr/bin/env python3
"""
Load A-share ETF OHLCV via the assistant repo's multi-source stack (plugins/data_collection),
aligned with openclaw-data-china-stock tooling — not Yahoo/yfinance.

Used by backtest.py / fetch_data.py so exec-based workflows avoid YFRateLimitError on CN ETFs.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np
import pandas as pd


def find_assistant_repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk parents from this file until we find etf-options-ai-assistant layout."""
    here = (start or Path(__file__)).resolve()
    for p in [here] + list(here.parents):
        if (p / "src" / "config_loader.py").is_file() and (
            p / "plugins" / "data_collection" / "etf" / "fetch_historical.py"
        ).is_file():
            return p
    return None


def normalize_cn_etf_code(symbol: str) -> Optional[str]:
    """
    Map 510300.SS / sh510300 / 510300 -> 510300.
    Returns None if the symbol does not look like a mainland ETF/stock numeric code.
    """
    s = symbol.strip().upper()
    if len(s) >= 8 and s[:2] in ("SH", "SZ") and s[2:].isdigit():
        return s[2:]
    for suf in (".SS", ".SZ", ".SH"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    s = s.replace(".", "")
    if s.isdigit() and len(s) == 6:
        return s
    return None


def is_cn_listed_numeric_symbol(symbol: str) -> bool:
    return normalize_cn_etf_code(symbol) is not None


def _load_fetch_historical_module(repo_root: Path) -> Any:
    path = repo_root / "plugins" / "data_collection" / "etf" / "fetch_historical.py"
    if not path.is_file():
        return None
    rs = str(repo_root)
    if rs not in sys.path:
        sys.path.insert(0, rs)
    spec = importlib.util.spec_from_file_location("_etf_fetch_historical_bt", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _chinese_etf_df_to_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    date_col = None
    for c in ("日期", "date", "trade_date", "datetime", "日期时间"):
        if c in df.columns:
            date_col = c
            break
    if date_col is None:
        return pd.DataFrame()

    def col(*names: str) -> pd.Series:
        for n in names:
            if n in df.columns:
                return pd.to_numeric(df[n], errors="coerce")
        return pd.Series(np.nan, index=df.index)

    idx = pd.to_datetime(df[date_col], errors="coerce")
    out = pd.DataFrame(
        {
            "open": col("开盘", "open"),
            "high": col("最高", "high"),
            "low": col("最低", "low"),
            "close": col("收盘", "close"),
            "volume": col("成交量", "volume", "vol"),
        }
    )
    out.index = idx
    out.index.name = "date"
    out = out.dropna(how="all", subset=["close"])
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def try_load_cn_etf_ohlcv(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    quiet: bool = False,
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Fetch ETF daily bars.

    Preferred path: merged tool `tool_fetch_etf_data` (historical) — same stack OpenClaw
    workflows use; preserves cache / source metadata including `as_of` when present.
    Fallback: `fetch_single_etf_historical` for legacy callers.
    """
    code = normalize_cn_etf_code(symbol)
    if code is None:
        return None, None

    repo = find_assistant_repo_root()
    if repo is None:
        if not quiet:
            print(
                "china_stock_loader: could not find assistant repo root "
                "(expected src/config_loader.py + plugins/data_collection/...).",
                file=sys.stderr,
            )
        return None, None

    rs = str(repo)
    if rs not in sys.path:
        sys.path.insert(0, rs)

    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")

    try:
        from plugins.merged.fetch_etf_data import tool_fetch_etf_data

        resp = tool_fetch_etf_data(
            data_type="historical",
            etf_code=code,
            period="daily",
            start_date=start_s,
            end_date=end_s,
        )
        if isinstance(resp, dict) and resp.get("success") and resp.get("data"):
            raw = pd.DataFrame(resp["data"])
            source = str(resp.get("source") or "tool_fetch_etf_data")
            ohlcv = _chinese_etf_df_to_ohlcv(raw)
            if not ohlcv.empty:
                ohlcv = ohlcv[(ohlcv.index >= pd.Timestamp(start)) & (ohlcv.index <= pd.Timestamp(end))]
                if ohlcv.index.tz is not None:
                    ohlcv.index = ohlcv.index.tz_localize(None)
                _as_of = resp.get("as_of") or resp.get("date")
                if _as_of is not None:
                    try:
                        ohlcv.attrs["as_of"] = _as_of  # type: ignore[attr-defined]
                    except Exception:
                        pass
                return ohlcv, source
    except Exception as e:
        if not quiet:
            print(f"china_stock_loader: tool_fetch_etf_data path failed: {e}", file=sys.stderr)

    mod = _load_fetch_historical_module(repo)
    if mod is None:
        if not quiet:
            print("china_stock_loader: failed to load fetch_historical module.", file=sys.stderr)
        return None, None

    try:
        raw, source = mod.fetch_single_etf_historical(
            code,
            period="daily",
            start_date=start_s,
            end_date=end_s,
            tushare_token=None,
            use_cache=True,
        )
    except Exception as e:
        if not quiet:
            print(f"china_stock_loader: fetch_single_etf_historical failed: {e}", file=sys.stderr)
        return None, None

    if raw is None or raw.empty:
        return None, source

    ohlcv = _chinese_etf_df_to_ohlcv(raw)
    if ohlcv.empty:
        return None, source

    ohlcv = ohlcv[(ohlcv.index >= pd.Timestamp(start)) & (ohlcv.index <= pd.Timestamp(end))]
    if ohlcv.index.tz is not None:
        ohlcv.index = ohlcv.index.tz_localize(None)

    return ohlcv, source


def resolve_data_source(preference: Optional[str] = None) -> str:
    """Normalize provider string (CLI/env fragment). Prefer ``skill_settings.effective_data_source`` for full precedence."""
    from skill_settings import normalize_data_source

    v = preference or os.environ.get("BACKTEST_DATA_SOURCE") or "auto"
    return normalize_data_source(v)


def should_try_china_first(source: str, symbol: str) -> bool:
    if source == "coingecko":
        return False
    if source == "china":
        return is_cn_listed_numeric_symbol(symbol)
    if source == "yfinance":
        return False
    # auto: CN numeric -> plugin-aligned path first
    return is_cn_listed_numeric_symbol(symbol)
