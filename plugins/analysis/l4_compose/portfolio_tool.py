from __future__ import annotations

from typing import Any, Dict

from plugins.analysis.l4_data_tools import tool_l4_valuation_context


def tool_l4_portfolio_valuation_context(
    weights: Dict[str, float],
    *,
    trade_date: str = "",
    aggregation: str = "weighted_avg_confidence",
) -> Dict[str, Any]:
    """
    持仓级 L4：按权重字典批量调用 tool_l4_valuation_context，聚合 confidence。

    weights: symbol -> weight（例如 {'600519': 0.4, '510300': 0.6}）；不要求和为 1，将归一化。
    """
    if not isinstance(weights, dict) or not weights:
        return {
            "success": False,
            "error": "weights_required",
            "data": {},
            "_meta": {
                "schema_name": "portfolio_valuation_context_v1",
                "schema_version": "1.0.0",
                "data_layer": "L4_data",
            },
        }

    tw = 0.0
    wnorm: dict[str, float] = {}
    for k, v in weights.items():
        try:
            w = float(v)
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        code = str(k).strip()
        if not code:
            continue
        wnorm[code] = w
        tw += w
    if tw <= 0:
        return {
            "success": False,
            "error": "no_positive_weights",
            "data": {},
            "_meta": {
                "schema_name": "portfolio_valuation_context_v1",
                "schema_version": "1.0.0",
                "data_layer": "L4_data",
            },
        }
    wnorm = {k: v / tw for k, v in wnorm.items()}

    per: list[dict[str, Any]] = []
    confidences: list[float] = []
    for sym, w in wnorm.items():
        raw = tool_l4_valuation_context(stock_code=sym, trade_date=trade_date or "")
        ok = bool(raw.get("success", True)) if isinstance(raw, dict) else False
        conf = None
        if isinstance(raw, dict):
            data = raw.get("data")
            if isinstance(data, dict):
                c = data.get("confidence")
                if isinstance(c, (int, float)):
                    conf = float(c)
            meta = raw.get("_meta")
            if conf is None and isinstance(meta, dict):
                c2 = meta.get("confidence")
                if isinstance(c2, (int, float)):
                    conf = float(c2)
        if conf is not None:
            confidences.append(conf * w)
        per.append(
            {
                "stock_code": sym,
                "weight": w,
                "success": ok,
                "confidence": conf,
                "raw_keys": list(raw.keys()) if isinstance(raw, dict) else [],
            }
        )

    if aggregation == "weighted_avg_confidence" and confidences:
        agg_conf = float(sum(confidences))
    else:
        vals = [p.get("confidence") for p in per if isinstance(p.get("confidence"), (int, float))]
        agg_conf = float(sum(vals) / len(vals)) if vals else None

    out_data = {
        "weights_normalized": wnorm,
        "per_symbol": per,
        "portfolio_confidence": agg_conf,
        "aggregation": aggregation,
    }

    return {
        "success": True,
        "data": out_data,
        "_meta": {
            "schema_name": "portfolio_valuation_context_v1",
            "schema_version": "1.0.0",
            "data_layer": "L4_data",
            "trade_date": trade_date or None,
            "symbols_count": len(wnorm),
        },
    }
