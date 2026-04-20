"""
Assistant-side policy news fetcher (Tavily, multi-key).

Why this exists:
- `plugins/data_collection` is a symlink to the OpenClaw runtime plugin directory, which we treat as read-only.
- We still want the assistant project to leverage `TAVILY_API_KEYS` multi-key rotation (incl. HTTP 432) reliably.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _coerce_items_from_tavily_raw(raw: Dict[str, Any], *, max_items: int) -> List[Dict[str, Any]]:
    results = raw.get("results") or []
    out: List[Dict[str, Any]] = []
    if not isinstance(results, list):
        return out
    for r in results:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "").strip()
        url = str(r.get("url") or "").strip()
        content = str(r.get("content") or r.get("snippet") or "").strip()
        if not title and not content:
            continue
        out.append(
            {
                "title": title,
                "url": url,
                "summary": content[:320] if content else "",
                "source": str(r.get("source") or "").strip(),
            }
        )
        if len(out) >= max(1, int(max_items)):
            break
    return out


def tool_fetch_policy_news(
    *,
    max_items: int = 5,
    days: int = 2,
    include_domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Fetch CN policy/macro market-moving news via Tavily.

    Returns a tool-style payload compatible with `send_daily_report`:
    - { success, message, data: { items, brief_answer, evidence_urls? } }
    """
    try:
        from plugins.utils.tavily_client import (
            DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS,
            tavily_search_with_include_domain_fallback,
        )
    except Exception as e:  # pragma: no cover
        return {"success": False, "message": f"import_error: {e}", "data": {"items": []}}

    mx = max(1, min(int(max_items), 10))
    dd = max(1, min(int(days), 7))
    dom = include_domains if isinstance(include_domains, list) and include_domains else DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS

    # Keep query broad but scoped to policy + A-shares market impact.
    query = (
        "中国 政策 要闻 影响 A股 市场 监管 央行 财政 产业政策 "
        "盘前 重要 新闻 摘要"
    )

    r = tavily_search_with_include_domain_fallback(
        query,
        max_results=max(4, mx + 2),
        topic="news",
        days=dd,
        deep=True,
        include_domains=dom[:12] if dom else None,
    )
    if not isinstance(r, dict) or not r.get("success"):
        msg = str((r or {}).get("message") or "tavily_failed").strip()
        return {"success": False, "message": msg, "data": {"items": [], "brief_answer": ""}}

    raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
    items = _coerce_items_from_tavily_raw(raw, max_items=mx)
    brief = str(r.get("answer") or "").strip()
    urls: List[str] = []
    for it in items:
        u = str(it.get("url") or "").strip()
        if u and u not in urls:
            urls.append(u)
    return {
        "success": True,
        "message": "ok",
        "data": {
            "items": items,
            "brief_answer": brief[:1800],
            "evidence_urls": urls[:10],
        },
    }

