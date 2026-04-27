from __future__ import annotations

from typing import Any, Dict

CANONICAL_SOURCE_IDS = {
    "akshare",
    "tushare",
    "mootdx",
    "sina",
    "eastmoney",
    "ths",
    "yfinance",
    "fmp",
    "tavily",
    "baostock",
    "efinance",
    "cache",
    "derived",
    "fallback",
    "unknown",
}


def canonical_source_id(raw_source: Any) -> str:
    s = str(raw_source or "").strip().lower()
    if not s:
        return "unknown"
    if s.startswith("eastmoney") or s.endswith("_em") or "eastmoney_http" in s:
        return "eastmoney"
    if s.startswith("sina") or "sinajs" in s or s.endswith("_sina"):
        return "sina"
    if s.startswith("ths") or "tonghuashun" in s or s.endswith("_ths"):
        return "ths"
    if s.startswith("akshare"):
        return "akshare"
    if s.startswith("tushare"):
        return "tushare"
    if s.startswith("financialmodelingprep") or s.startswith("fmp"):
        return "fmp"
    if s == "yfinance":
        return "yfinance"
    if s.startswith("mootdx"):
        return "mootdx"
    if s.startswith("baostock"):
        return "baostock"
    if s.startswith("efinance"):
        return "efinance"
    if s.startswith("tavily"):
        return "tavily"
    if s.startswith("cache"):
        return "cache"
    if s in {"fallback", "none"}:
        return "fallback"
    if s in CANONICAL_SOURCE_IDS:
        return s
    return "unknown"


def with_source_meta(
    payload: Dict[str, Any],
    *,
    source_raw: str,
    source_stage: str = "primary",
    source_interface: str = "",
    source_vendor: str = "",
) -> Dict[str, Any]:
    out = dict(payload)
    sid = canonical_source_id(source_raw)
    out["source"] = source_raw
    out["source_id"] = sid
    out["source_raw"] = source_raw
    out["source_stage"] = source_stage
    if source_interface:
        out["source_interface"] = source_interface
    if source_vendor:
        out["source_vendor"] = source_vendor
    elif sid not in {"unknown", "fallback"}:
        out["source_vendor"] = sid
    return out
