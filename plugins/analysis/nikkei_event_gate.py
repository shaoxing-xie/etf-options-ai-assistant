from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Optional, Tuple


IMPACT_TEMPLATES: Dict[str, str] = {
    "BOJ会议": "日银政策变化影响日元汇率→日股开盘",
    "FOMC": "隔夜美盘情绪→日经期货→次日开盘",
    "日本CPI": "影响日银加息预期→汇率→股市",
    "美国CPI": "影响美联储政策→美元/日元→日股",
}


def _safe_date(v: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(v or "").strip(), "%Y-%m-%d")
    except Exception:
        return None


def _fetch_tavily_events(trade_date: str, timeout_s: float = 8.0) -> Dict[str, Any]:
    try:
        from plugins.utils.tavily_client import tavily_search_with_include_domain_fallback
    except Exception as e:
        return {"success": False, "note": f"tavily_import_error:{type(e).__name__}", "events": []}
    query = (
        "Nikkei 225 overnight risk events around "
        f"{trade_date}: BOJ meeting, Japan CPI GDP Tankan, "
        "FOMC, US CPI, NFP, China GDP PMI. Return event names and timing."
    )
    try:
        _ = timeout_s
        res = tavily_search_with_include_domain_fallback(query, topic="news", days=3, deep=True, max_results=8)
    except Exception as e:
        return {"success": False, "note": f"tavily_query_error:{type(e).__name__}", "events": []}
    if not isinstance(res, dict) or not res.get("success"):
        return {"success": False, "note": str((res or {}).get("message") or "tavily_failed"), "events": []}
    raw = res.get("raw") if isinstance(res.get("raw"), dict) else {}
    chunks: List[str] = [str(res.get("answer") or "")]
    for r in (raw.get("results") or [])[:8]:
        if isinstance(r, dict):
            chunks.append(str(r.get("title") or ""))
            chunks.append(str(r.get("content") or r.get("snippet") or ""))
    return {"success": True, "note": "tavily_ok", "events": _extract_events(" ".join(chunks).lower())}


def _fetch_event_sentinel_events(trade_date: str, timeout_s: float = 8.0) -> Dict[str, Any]:
    try:
        from plugins.sentinel.event_sentinel import tool_event_sentinel
    except Exception as e:
        return {"success": False, "note": f"event_sentinel_import_error:{type(e).__name__}", "events": []}
    query = (
        "Nikkei 225 risk events around "
        f"{trade_date}: BOJ, Japan CPI GDP Tankan, FOMC, US CPI NFP, China GDP PMI."
    )
    try:
        _ = timeout_s
        res = tool_event_sentinel(query=query, topic="news", n=8, days=3, deep=True)
    except Exception as e:
        return {"success": False, "note": f"event_sentinel_query_error:{type(e).__name__}", "events": []}
    if not isinstance(res, dict) or not bool(res.get("success")):
        return {"success": False, "note": str((res or {}).get("message") or "event_sentinel_failed"), "events": []}
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    chunks: List[str] = [str(data.get("answer") or "")]
    for src in (data.get("sources") or []):
        if isinstance(src, dict):
            chunks.append(str(src.get("title") or ""))
            chunks.append(str(src.get("url") or ""))
    return {"success": True, "note": "event_sentinel_ok", "events": _extract_events(" ".join(chunks).lower())}


def _extract_events(text: str) -> List[str]:
    out: List[str] = []
    patterns: List[Tuple[str, str]] = [
        ("BOJ会议", r"\bboj\b|bank of japan|日银|日本央行"),
        ("日本CPI", r"japan cpi|日本cpi"),
        ("日本GDP", r"japan gdp|日本gdp"),
        ("Tankan", r"tankan"),
        ("FOMC", r"\bfomc\b|federal reserve"),
        ("美国CPI", r"us cpi|美国cpi"),
        ("美国非农", r"\bnfp\b|nonfarm payroll"),
        ("中国GDP", r"china gdp|中国gdp"),
        ("中国PMI", r"china pmi|中国pmi"),
    ]
    for name, pat in patterns:
        if re.search(pat, text):
            out.append(name)
    return out[:8]


def _risk_from_event(name: str) -> float:
    if name in {"BOJ会议", "FOMC", "美国CPI", "美国非农", "中国GDP"}:
        return 0.25
    if name in {"日本CPI", "日本GDP", "Tankan", "中国PMI"}:
        return 0.18
    return 0.1


def calculate_event_gate(trade_date: str) -> Dict[str, Any]:
    td = _safe_date(trade_date)
    tav = _fetch_tavily_events(trade_date)
    sentinel = _fetch_event_sentinel_events(trade_date)
    events: List[str] = []
    for src in (tav, sentinel):
        for e in (src.get("events") or []):
            if isinstance(e, str) and e not in events:
                events.append(e)
    source_status = "ok" if any(bool(x.get("success")) for x in (tav, sentinel)) else "degraded"
    # static fallback: BOJ/fed-like risk day proxy (weekday based)
    if not events and td is not None and td.weekday() in {2, 3}:
        events.append("FOMC")
    risk = 0.0
    for e in events:
        risk += _risk_from_event(e)
    risk = min(risk, 0.8)
    impacts = [{"event": e, "impact_note": IMPACT_TEMPLATES.get(e, "事件扰动提升隔夜不确定性")} for e in events[:5]]
    note = "nikkei_event_gate_ok" if source_status == "ok" else "nikkei_event_gate_degraded"
    return {
        "event_risk": round(float(risk), 4),
        "event_triggers": events[:8],
        "impact_templates": impacts,
        "event_note": note,
        "source_status": source_status,
        "source_details": {"tavily": tav, "event_sentinel": sentinel},
    }

