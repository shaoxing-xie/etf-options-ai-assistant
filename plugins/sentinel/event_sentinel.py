"""
事件哨兵（工具层）。

用途：
- 将外部事件/政策/公告等信息快速总结成“对宽基ETF/A股的潜在影响”。
- 提供结构化结果，供 trading-copilot 决定是否触发再分析（重流程）。

说明：
- 默认使用 Tavily API（需要 TAVILY_API_KEY）。
- 在网络受限环境中会降级返回可执行的提示（让用户粘贴事件要点或在生产环境启用网络）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz


def _now_cn() -> str:
    tz = pytz.timezone("Asia/Shanghai")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def _safe_str(x: Any) -> str:
    return str(x) if x is not None else ""


def _compact_sources(results: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in (results or [])[: max(1, min(n, 10))]:
        title = _safe_str(r.get("title")).strip()
        url = _safe_str(r.get("url")).strip()
        content = _safe_str(r.get("content")).strip()
        score = r.get("score")
        if not title or not url:
            continue
        out.append(
            {
                "title": title,
                "url": url,
                "score": float(score) if isinstance(score, (int, float)) else None,
                "snippet": content[:300] if content else None,
            }
        )
    return out


def _basic_impact_guess(query: str) -> Dict[str, Any]:
    """
    极简影响标签：用于无网络或无key时给出可执行结构，避免空返回。
    生产环境建议替换为更精细的事件分类器。
    """
    q = query.lower()
    tags: List[str] = []
    if any(k in q for k in ["降准", "降息", "利率", "央行", "mlf", "lpr"]):
        tags += ["macro_liquidity", "rate"]
    if any(k in q for k in ["关税", "制裁", "战争", "地缘", "oil", "原油"]):
        tags += ["geopolitics", "risk_off"]
    if any(k in q for k in ["cpi", "ppi", "通胀", "就业"]):
        tags += ["macro_data"]
    if any(k in q for k in ["监管", "证监会", "新规", "交易规则"]):
        tags += ["regulation"]
    if any(k in q for k in ["业绩", "公告", "财报", "分红", "减持"]):
        tags += ["company_event"]
    if not tags:
        tags = ["unknown"]
    return {"tags": tags, "confidence": 0.3}


def _tavily_search(
    *,
    query: str,
    n: int,
    topic: str,
    days: Optional[int],
    deep: bool,
) -> Dict[str, Any]:
    try:
        from plugins.utils.tavily_client import tavily_post_search
    except Exception as e:
        return {"success": False, "message": f"Tavily import error: {e}", "data": None}

    body: Dict[str, Any] = {
        "query": query,
        "search_depth": "advanced" if deep else "basic",
        "topic": topic,
        "max_results": max(1, min(int(n), 20)),
        "include_answer": True,
        "include_raw_content": False,
    }
    if topic == "news" and days:
        body["days"] = int(days)
    post = tavily_post_search(body, timeout=20)
    if post.get("success") and isinstance(post.get("data"), dict):
        return {"success": True, "data": post["data"]}
    return {
        "success": False,
        "message": post.get("message") or "Tavily failed",
        "data": None,
    }


def tool_event_sentinel(
    query: str,
    *,
    topic: str = "news",
    n: int = 5,
    days: int = 3,
    deep: bool = False,
    disable_network_fetch: bool = False,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：事件哨兵

    Args:
        query: 事件/政策/公告关键词或一句话描述
        topic: tavily topic（general|news），默认 news
        n: sources 数量
        days: news 回溯天数
        deep: 是否深搜
        disable_network_fetch: 禁用联网（受限环境降级）
    """
    if not query or not str(query).strip():
        return {"success": False, "message": "query 不能为空", "data": None}

    now = _now_cn()
    impact_hint = _basic_impact_guess(query)

    if disable_network_fetch:
        return {
            "success": True,
            "message": "network_fetch_disabled",
            "data": {
                "timestamp": now,
                "query": query,
                "impact_hint": impact_hint,
                "answer": None,
                "sources": [],
                "should_trigger_reanalysis": False,
                "note": "当前运行环境禁用联网抓取；请在生产环境启用网络或粘贴事件要点让我做影响评估。",
            },
        }

    tav = _tavily_search(query=query, n=n, topic=topic, days=days, deep=deep)
    if not tav.get("success"):
        return {
            "success": True,
            "message": "tavily_unavailable",
            "data": {
                "timestamp": now,
                "query": query,
                "impact_hint": impact_hint,
                "answer": None,
                "sources": [],
                "should_trigger_reanalysis": False,
                "note": tav.get("message") or "tavily unavailable",
            },
        }

    data = tav.get("data") or {}
    answer = data.get("answer")
    results = data.get("results") or []
    sources = _compact_sources(results, n=n)

    # 简单触发规则：若有 answer 且 sources>=2，建议触发再分析
    should_trigger = bool(answer) and len(sources) >= 2

    return {
        "success": True,
        "message": "event-sentinel ok",
        "data": {
            "timestamp": now,
            "query": query,
            "impact_hint": impact_hint,
            "answer": answer,
            "sources": sources,
            "should_trigger_reanalysis": should_trigger,
        },
    }

