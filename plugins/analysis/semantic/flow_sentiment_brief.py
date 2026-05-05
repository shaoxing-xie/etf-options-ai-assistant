from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from plugins.analysis.semantic.common import confidence_from_quality, merge_upstream_quality, semantic_meta
from plugins.analysis.semantic.narrative import cn_for_key, flow_score_label, load_rules
from plugins.data_collection.a_share_fund_flow import tool_fetch_a_share_fund_flow


def _top_sector_names(records: List[Dict[str, Any]], n: int = 3) -> List[str]:
    out: List[str] = []
    for r in records[: max(n * 4, 20)]:
        if not isinstance(r, dict):
            continue
        name = r.get("板块名称") or r.get("行业") or r.get("名称") or r.get("sector_name")
        if name and str(name).strip():
            out.append(str(name).strip())
        if len(out) >= n:
            break
    return out[:n]


def tool_semantic_flow_sentiment_brief(
    trade_date: str = "",
    sector_window: str = "d5",
    limit: int = 8,
) -> Dict[str, Any]:
    """
    L4-semantic：A 股资金流向与板块热度摘要（模板）。非买卖建议。
    """
    td = (trade_date or "").strip() or datetime.now().strftime("%Y-%m-%d")
    rules = load_rules()
    lineage = ["tool_fetch_a_share_fund_flow"]

    mh = tool_fetch_a_share_fund_flow(
        query_kind="market_history",
        provider_preference="auto",
        max_days=30,
    )
    sr = tool_fetch_a_share_fund_flow(
        query_kind="sector_rank",
        sector_type="industry",
        rank_window=sector_window,
        limit=min(int(limit), 50),
        provider_preference="auto",
    )

    q_m = str(mh.get("quality_status") or mh.get("data_quality") or ("ok" if mh.get("success") else "degraded"))
    q_s = str(sr.get("quality_status") or sr.get("data_quality") or ("ok" if sr.get("success") else "degraded"))
    if not mh.get("success"):
        q_m = "degraded"
    if not sr.get("success"):
        q_s = "degraded"

    q = merge_upstream_quality(q_m, q_s)

    flow_score = None
    if isinstance(mh, dict):
        flow_score = mh.get("flow_score")
        try:
            flow_score = float(flow_score) if flow_score is not None else None
        except (TypeError, ValueError):
            flow_score = None

    fs_key = flow_score_label(flow_score, rules)
    fs_cn = cn_for_key(fs_key)

    records = sr.get("records") if isinstance(sr.get("records"), list) else []
    tops = _top_sector_names(records, 3)

    cum5 = None
    if isinstance(mh.get("cumulative"), dict):
        cum5 = mh["cumulative"].get("5d")

    parts = [fs_cn]
    if cum5 is not None:
        parts.append(f"近端资金合计（5日 proxy 累计）约 {cum5}。")
    if tops:
        parts.append(f"板块净流入排名靠前示例：{' / '.join(tops)}。")
    else:
        parts.append("板块排名明细暂不可用或为空。")

    summary = "".join(parts)

    base_conf = 0.78 if q == "ok" else 0.5
    conf = confidence_from_quality(base_conf, q)

    return {
        "success": q != "error",
        "message": "flow_sentiment_brief ok" if q == "ok" else f"flow_sentiment_brief {q}",
        "quality_status": q,
        "_meta": semantic_meta(
            schema_name="flow_sentiment_brief_v1",
            schema_version="1.0.0",
            task_id="semantic-flow-sentiment-brief",
            trade_date=td,
            data_layer="L4_semantic",
            lineage_refs=lineage,
            quality_status=q,
            confidence=conf,
            source_tools=["tool_fetch_a_share_fund_flow"],
        ),
        "data": {
            "summary": summary,
            "flow_score": flow_score,
            "flow_sentiment_key": fs_key,
            "top_sectors_sample": tops,
            "market_history_success": bool(mh.get("success")),
            "sector_rank_success": bool(sr.get("success")),
        },
    }
