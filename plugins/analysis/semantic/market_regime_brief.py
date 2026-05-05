from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from plugins.analysis.market_regime import tool_detect_market_regime
from plugins.analysis.semantic.common import confidence_from_quality, merge_upstream_quality, semantic_meta
from plugins.analysis.semantic.narrative import cn_for_key, load_rules, regime_display_key
from plugins.data_collection.limit_up.sector_heat import tool_sector_heat_score
from plugins.merged.fetch_index_data import tool_fetch_index_data


def tool_semantic_market_regime_brief(
    benchmark_etf: str = "510300",
    index_code: str = "000001",
    mode: str = "prod",
    trade_date: str = "",
    include_sector_heat: bool = True,
) -> Dict[str, Any]:
    """
    L4-semantic：综合市场 regime（研究标签）+ 上证综指快照 + 可选板块热度摘要。
    """
    td = (trade_date or "").strip() or datetime.now().strftime("%Y-%m-%d")
    rules = load_rules()
    lineage: List[str] = ["tool_detect_market_regime", "tool_fetch_index_data"]

    mr = tool_detect_market_regime(symbol=str(benchmark_etf).strip() or "510300", mode=str(mode or "prod"))
    ix = tool_fetch_index_data(data_type="realtime", index_code=str(index_code).strip() or "000001")

    q_mr = "ok" if mr.get("success") else "degraded"
    q_ix = "ok" if ix.get("success") else "degraded"

    regime = None
    mr_conf = None
    feats = {}
    if isinstance(mr.get("data"), dict):
        regime = mr["data"].get("regime")
        mr_conf = mr["data"].get("confidence")
        feats = mr["data"].get("features") if isinstance(mr["data"].get("features"), dict) else {}

    idx_pct = None
    idx_last = None
    raw_ix = ix.get("data")
    if isinstance(raw_ix, dict):
        idx_pct = raw_ix.get("change_percent") or raw_ix.get("change_pct") or raw_ix.get("pct_chg")
        idx_last = raw_ix.get("close") or raw_ix.get("最新价") or raw_ix.get("price")
    elif isinstance(raw_ix, list) and raw_ix:
        row = raw_ix[0] if isinstance(raw_ix[0], dict) else {}
        idx_pct = row.get("change_pct") or row.get("pct_chg")
        idx_last = row.get("close") or row.get("price")

    sector_note = ""
    q_sh = "skipped"
    if include_sector_heat:
        lineage.append("tool_sector_heat_score")
        try:
            sh = tool_sector_heat_score(date=None)
            q_sh = "ok" if sh.get("success") else "degraded"
            secs = sh.get("sectors") if isinstance(sh.get("sectors"), list) else []
            names = []
            for s in secs[:3]:
                if isinstance(s, dict) and s.get("name"):
                    names.append(str(s["name"]))
            if names:
                sector_note = f"涨停口径板块热度前三示例：{' / '.join(names)}。"
        except Exception:
            q_sh = "degraded"
            sector_note = "板块热度暂不可用。"

    q = merge_upstream_quality(q_mr, q_ix, q_sh if include_sector_heat else q_mr)

    rk = regime_display_key(str(regime or ""), rules)
    rk_cn = cn_for_key(rk)

    pct_s = f"{float(idx_pct):.2f}%" if idx_pct is not None and str(idx_pct).strip() != "" else "—"
    last_s = str(idx_last) if idx_last is not None else "—"

    summary_parts = [
        f"基准 ETF「{benchmark_etf}」研究 regime={regime or 'unknown'}（{rk_cn}）。",
        f"指数「{index_code}」快照涨跌约 {pct_s} ，点位/最新≈{last_s}。",
    ]
    if sector_note:
        summary_parts.append(sector_note)
    if feats:
        m20 = feats.get("momentum_20d")
        if m20 is not None:
            try:
                summary_parts.append(f"（特征）20 日动量≈{float(m20)*100:.2f}%。")
            except (TypeError, ValueError):
                pass

    summary = "".join(summary_parts)

    base_conf = float(mr_conf) if isinstance(mr_conf, (int, float)) else 0.72
    conf = confidence_from_quality(min(0.9, max(0.35, base_conf)), q)

    return {
        "success": q != "error",
        "message": "market_regime_brief ok" if q == "ok" else f"market_regime_brief {q}",
        "quality_status": q,
        "_meta": semantic_meta(
            schema_name="market_regime_brief_v1",
            schema_version="1.0.0",
            task_id="semantic-market-regime-brief",
            trade_date=td,
            data_layer="L4_semantic",
            lineage_refs=lineage,
            quality_status=q,
            confidence=conf,
            source_tools=[
                "tool_detect_market_regime",
                "tool_fetch_index_data",
                *(["tool_sector_heat_score"] if include_sector_heat else []),
            ],
        ),
        "data": {
            "summary": summary,
            "regime": regime,
            "regime_label_key": rk,
            "benchmark_etf": str(benchmark_etf),
            "index_code": str(index_code),
            "index_change_pct": idx_pct,
            "features": feats,
        },
    }
