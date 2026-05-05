from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from plugins.analysis.l4_compose.portfolio_tool import tool_l4_portfolio_valuation_context
from plugins.analysis.l4_data_tools import tool_l4_pe_ttm_percentile
from plugins.analysis.semantic.common import confidence_from_quality, merge_upstream_quality, semantic_meta
from plugins.analysis.semantic.narrative import load_rules, pick_percentile_label, cn_for_key


def _hhi(weights: Dict[str, float]) -> float:
    if not weights:
        return 0.0
    return float(sum(w * w for w in weights.values()))


def tool_semantic_portfolio_concentration_brief(
    weights: Dict[str, Any],
    trade_date: str = "",
    window_years: int = 5,
    max_symbols: int = 25,
) -> Dict[str, Any]:
    """
    L4-semantic：持仓集中度 + 组合估值上下文摘要（基于 L4-data 聚合）。非买卖建议。
    """
    td = (trade_date or "").strip() or datetime.now().strftime("%Y-%m-%d")
    rules = load_rules()
    lineage = ["tool_l4_portfolio_valuation_context", "tool_l4_pe_ttm_percentile"]

    if not isinstance(weights, dict) or not weights:
        return {
            "success": False,
            "message": "weights_required",
            "quality_status": "error",
            "_meta": semantic_meta(
                schema_name="portfolio_concentration_brief_v1",
                schema_version="1.0.0",
                task_id="semantic-portfolio-concentration-brief",
                trade_date=td,
                data_layer="L4_semantic",
                lineage_refs=lineage,
                quality_status="error",
                confidence=0.0,
            ),
            "data": {"summary": "缺少持仓权重字典。", "weights": {}},
        }

    wnorm: Dict[str, float] = {}
    for k, v in weights.items():
        try:
            w = float(v)
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        code = str(k).strip()
        if code:
            wnorm[code] = w
    tw = sum(wnorm.values())
    if tw <= 0:
        return {
            "success": False,
            "message": "no_positive_weights",
            "quality_status": "error",
            "_meta": semantic_meta(
                schema_name="portfolio_concentration_brief_v1",
                schema_version="1.0.0",
                task_id="semantic-portfolio-concentration-brief",
                trade_date=td,
                data_layer="L4_semantic",
                lineage_refs=lineage,
                quality_status="error",
                confidence=0.0,
            ),
            "data": {"summary": "权重无效。", "weights": {}},
        }
    wnorm = {k: v / tw for k, v in wnorm.items()}

    keys = list(wnorm.keys())[: max(1, min(int(max_symbols), 50))]
    w_small = {k: wnorm[k] for k in keys}

    pv = tool_l4_portfolio_valuation_context(weights=w_small, trade_date=td)
    q_pv = str(pv.get("_meta", {}).get("quality_status") or ("ok" if pv.get("success") else "degraded"))

    per_rows: List[Tuple[str, float, Optional[float], str]] = []
    qs: List[str] = [q_pv]
    for sym, w in sorted(w_small.items(), key=lambda x: -x[1]):
        pr = tool_l4_pe_ttm_percentile(stock_code=sym, trade_date=td, window_years=int(window_years))
        qs.append(str(pr.get("quality_status") or "degraded"))
        pct = None
        if isinstance(pr.get("data"), dict):
            pct = pr["data"].get("percentile_0_100")
            try:
                pct = float(pct) if pct is not None else None
            except (TypeError, ValueError):
                pct = None
        lbl = pick_percentile_label(pct, rules)
        per_rows.append((sym, w, pct, lbl))

    q = merge_upstream_quality(*qs)

    hhi = _hhi({k: w_small[k] for k in w_small})
    top_sym = max(w_small.items(), key=lambda x: x[1])[0]
    top_w = w_small[top_sym]

    thr_hhi = float((rules.get("portfolio") or {}).get("concentration", {}).get("hhi_high_threshold") or 0.35)
    thr_top = float((rules.get("portfolio") or {}).get("concentration", {}).get("top_weight_high_threshold") or 0.45)

    conc_parts = []
    if hhi >= thr_hhi:
        conc_parts.append(f"集中度指标 HHI≈{hhi:.2f}（偏高）。")
    else:
        conc_parts.append(f"集中度指标 HHI≈{hhi:.2f}。")
    if top_w >= thr_top:
        conc_parts.append(f"单一标的权重 {top_sym}≈{top_w*100:.1f}%（偏高）。")

    lines = ["；".join(conc_parts)]
    for sym, w, pct, lbl in per_rows[:8]:
        pct_s = f"{pct:.1f}" if pct is not None and pct == pct else "—"
        lines.append(f"- {sym} 权重≈{w*100:.1f}% ：PE 分位≈{pct_s}%（{cn_for_key(lbl)}）")

    summary = "\n".join(lines)

    pdata = pv.get("data") if isinstance(pv.get("data"), dict) else {}
    pconf = pdata.get("portfolio_confidence")

    base_conf = 0.7 if q == "ok" else 0.45
    if isinstance(pconf, (int, float)):
        base_conf = min(0.9, max(base_conf, float(pconf)))
    conf = confidence_from_quality(base_conf, q)

    return {
        "success": q != "error",
        "message": "portfolio_concentration_brief ok" if q == "ok" else f"portfolio_concentration_brief {q}",
        "quality_status": q,
        "_meta": semantic_meta(
            schema_name="portfolio_concentration_brief_v1",
            schema_version="1.0.0",
            task_id="semantic-portfolio-concentration-brief",
            trade_date=td,
            data_layer="L4_semantic",
            lineage_refs=lineage,
            quality_status=q,
            confidence=conf,
            source_tools=["tool_l4_portfolio_valuation_context", "tool_l4_pe_ttm_percentile"],
        ),
        "data": {
            "summary": summary,
            "hhi": round(hhi, 4),
            "top_symbol": top_sym,
            "top_weight": round(top_w, 6),
            "symbols_evaluated": list(w_small.keys()),
            "per_symbol_brief": [
                {"symbol": s, "weight": w, "pe_percentile_0_100": p, "band_key": lbl}
                for s, w, p, lbl in per_rows
            ],
            "portfolio_context": pdata,
        },
    }
