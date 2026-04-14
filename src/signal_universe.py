"""
解析 signal_generation + option_contracts，供三类信号工具统一选取标的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ResolvedOptionTarget:
    underlying: str
    index_symbol: str
    enabled: bool
    row: Dict[str, Any]
    max_contracts_per_side: int


@dataclass
class ResolvedEtfTarget:
    symbol: str
    index_benchmark: str
    name: Optional[str]


@dataclass
class ResolvedStockTarget:
    symbol: str
    name: Optional[str]


def _first_enabled_watchlist(watchlist: List[Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(watchlist, list):
        return None
    for w in watchlist:
        if isinstance(w, dict) and w.get("enabled", True):
            return w
    return None


def resolve_option_target(config: Dict[str, Any], underlying: Optional[str] = None) -> ResolvedOptionTarget:
    sg = config.get("signal_generation") or {}
    opt = sg.get("option") or {}
    default_u = str(opt.get("default_underlying") or "510300")
    max_cc = int(opt.get("max_contracts_per_side") or 8)
    u_req = None
    if underlying is not None:
        s = str(underlying).strip()
        if s:
            u_req = s
    u = u_req or default_u

    oc = config.get("option_contracts") or {}
    rows = oc.get("underlyings") or []
    row: Optional[Dict[str, Any]] = None
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            if str(r.get("underlying")) == str(u):
                row = r
                break
        if row is None and rows:
            first = rows[0]
            if isinstance(first, dict):
                row = first
                u = str(first.get("underlying", u))

    if row is None:
        row = {
            "underlying": u,
            "index_symbol": "000300",
            "enabled": True,
            "call_contracts": [],
            "put_contracts": [],
        }

    idx = str(row.get("index_symbol") or "000300")
    enabled = bool(row.get("enabled", True))
    return ResolvedOptionTarget(
        underlying=str(row.get("underlying", u)),
        index_symbol=idx,
        enabled=enabled,
        row=row,
        max_contracts_per_side=max_cc,
    )


def resolve_etf_target(config: Dict[str, Any], etf_symbol: Optional[str] = None) -> Optional[ResolvedEtfTarget]:
    sg = (config.get("signal_generation") or {}).get("etf") or {}
    if sg.get("enabled") is False:
        return None
    default_sym = str(sg.get("default_symbol") or "510300")
    wl = sg.get("watchlist") or []

    if etf_symbol is not None and str(etf_symbol).strip():
        es = str(etf_symbol).strip()
        for w in wl if isinstance(wl, list) else []:
            if isinstance(w, dict) and str(w.get("symbol")) == es and w.get("enabled", True):
                return ResolvedEtfTarget(
                    symbol=es,
                    index_benchmark=str(w.get("index_benchmark") or "000300"),
                    name=w.get("name"),
                )

    pick = _first_enabled_watchlist(wl if isinstance(wl, list) else [])
    if pick:
        return ResolvedEtfTarget(
            symbol=str(pick.get("symbol") or default_sym),
            index_benchmark=str(pick.get("index_benchmark") or "000300"),
            name=pick.get("name"),
        )
    return ResolvedEtfTarget(symbol=default_sym, index_benchmark="000300", name=None)


def resolve_stock_target(config: Dict[str, Any], stock_symbol: Optional[str] = None) -> Optional[ResolvedStockTarget]:
    sg = (config.get("signal_generation") or {}).get("stock") or {}
    if sg.get("enabled") is False:
        return None
    default_sym = str(sg.get("default_symbol") or "600519")
    wl = sg.get("watchlist") or []

    if stock_symbol is not None and str(stock_symbol).strip():
        ss = str(stock_symbol).strip()
        for w in wl if isinstance(wl, list) else []:
            if isinstance(w, dict) and str(w.get("symbol")) == ss and w.get("enabled", True):
                return ResolvedStockTarget(symbol=ss, name=w.get("name"))

    pick = _first_enabled_watchlist(wl if isinstance(wl, list) else [])
    if pick:
        return ResolvedStockTarget(
            symbol=str(pick.get("symbol") or default_sym),
            name=pick.get("name"),
        )
    return ResolvedStockTarget(symbol=default_sym, name=None)
