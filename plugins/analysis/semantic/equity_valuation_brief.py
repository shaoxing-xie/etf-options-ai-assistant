from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from plugins.analysis.l4_data_tools import tool_l4_pe_ttm_percentile, tool_l4_valuation_context
from plugins.analysis.semantic.common import confidence_from_quality, merge_upstream_quality, semantic_meta
from plugins.analysis.semantic.narrative import (
    load_rules,
    pick_percentile_label,
    template_valuation_summary,
)
from plugins.data_collection.entity.entity_tools import tool_resolve_symbol


def tool_semantic_equity_valuation_brief(
    symbol: str,
    trade_date: str = "",
    window_years: int = 5,
) -> Dict[str, Any]:
    """
    L4-semantic：单标的估值摘要（PE/PB + 分位带 + 一句话模板）。非买卖建议。
    """
    td = (trade_date or "").strip() or datetime.now().strftime("%Y-%m-%d")
    rules = load_rules()
    lineage: List[str] = ["tool_resolve_symbol", "tool_l4_valuation_context", "tool_l4_pe_ttm_percentile"]

    res = tool_resolve_symbol(symbol or "")
    q_resolve = str(res.get("quality_status") or "error")
    if not res.get("success"):
        return {
            "success": False,
            "message": res.get("message") or "resolve_failed",
            "quality_status": merge_upstream_quality(q_resolve),
            "_meta": semantic_meta(
                schema_name="equity_valuation_brief_v1",
                schema_version="1.0.0",
                task_id="semantic-equity-valuation-brief",
                trade_date=td,
                data_layer="L4_semantic",
                lineage_refs=lineage,
                quality_status="error",
                confidence=0.0,
                source_tools=["tool_resolve_symbol"],
            ),
            "data": {"summary": "无法解析标的代码。", "symbol_input": symbol},
        }

    data_r = res.get("data") if isinstance(res.get("data"), dict) else {}
    code = str(data_r.get("canonical_code") or "").strip()
    etype = str(data_r.get("entity_type") or "")
    if not code:
        return {
            "success": False,
            "message": "missing canonical_code",
            "quality_status": "error",
            "_meta": semantic_meta(
                schema_name="equity_valuation_brief_v1",
                schema_version="1.0.0",
                task_id="semantic-equity-valuation-brief",
                trade_date=td,
                data_layer="L4_semantic",
                lineage_refs=lineage,
                quality_status="error",
                confidence=0.0,
            ),
            "data": {},
        }

    display_name = f"{etype}:{code}"

    vc = tool_l4_valuation_context(stock_code=code, trade_date=td)
    pe_row = tool_l4_pe_ttm_percentile(stock_code=code, trade_date=td, window_years=int(window_years))

    q_v = merge_upstream_quality(
        q_resolve,
        str(vc.get("quality_status")),
        str(pe_row.get("quality_status")),
    )

    metrics = {}
    if isinstance(vc.get("data"), dict):
        metrics = vc["data"].get("metrics") if isinstance(vc["data"].get("metrics"), dict) else {}

    pe = metrics.get("pe")
    pb = metrics.get("pb")
    pct = None
    if isinstance(pe_row.get("data"), dict):
        pct = pe_row["data"].get("percentile_0_100")

    try:
        pe_f = float(pe) if pe is not None else None
    except (TypeError, ValueError):
        pe_f = None
    try:
        pb_f = float(pb) if pb is not None else None
    except (TypeError, ValueError):
        pb_f = None
    try:
        pct_f = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pct_f = None

    label_key = pick_percentile_label(pct_f, rules)
    summary = template_valuation_summary(
        name=display_name,
        code=code,
        pe=pe_f,
        pb=pb_f,
        pct=pct_f,
        label_key=label_key,
        window_years=int(window_years),
    )

    base_conf = 0.82 if q_v == "ok" else 0.55
    conf = confidence_from_quality(base_conf, q_v)

    return {
        "success": q_v != "error",
        "message": "equity_valuation_brief ok" if q_v == "ok" else f"equity_valuation_brief {q_v}",
        "quality_status": q_v,
        "_meta": semantic_meta(
            schema_name="equity_valuation_brief_v1",
            schema_version="1.0.0",
            task_id="semantic-equity-valuation-brief",
            trade_date=td,
            data_layer="L4_semantic",
            lineage_refs=lineage,
            quality_status=q_v,
            confidence=conf,
            source_tools=["tool_resolve_symbol", "tool_l4_valuation_context", "tool_l4_pe_ttm_percentile"],
        ),
        "data": {
            "summary": summary,
            "canonical_code": code,
            "entity_type": etype,
            "valuation_level_key": label_key,
            "pe": pe_f,
            "pb": pb_f,
            "pe_percentile_0_100": pct_f,
            "window_years": int(window_years),
        },
    }
