from __future__ import annotations

from typing import Any, Dict, List

from .common import clamp, result, safe_float


def predict_csi300(index_features: Dict[str, Any], *, trade_date: str, predict_for_trade_date: str) -> Dict[str, Any]:
    reasons: List[str] = []
    northbound = index_features.get("northbound") if isinstance(index_features.get("northbound"), dict) else {}
    macro_proxy = index_features.get("macro_proxy") if isinstance(index_features.get("macro_proxy"), dict) else {}

    north_score = safe_float(northbound.get("northbound_intraday_score"))
    macro_score = safe_float(macro_proxy.get("macro_proxy_score"))
    weight_multiplier = safe_float(macro_proxy.get("macro_weight_multiplier"))
    valuation_pct = safe_float(index_features.get("valuation_proxy_percentile"))

    if north_score is None:
        reasons.append("missing_northbound_score")
        north_score = 0.0
    if macro_score is None:
        reasons.append("missing_macro_proxy_score")
        macro_score = 0.0
    if weight_multiplier is None:
        weight_multiplier = 0.0
    if valuation_pct is None:
        reasons.append("missing_valuation_proxy_percentile")
        valuation_pct = 50.0

    valuation_score = 0.15 if valuation_pct < 30 else -0.15 if valuation_pct > 70 else 0.0
    macro_component = macro_score * weight_multiplier
    north_component = clamp(north_score, -1.0, 1.0) * 0.35
    macro_component = clamp(macro_component, -1.0, 1.0) * 0.35
    value_component = valuation_score * 0.30
    score = north_component + macro_component + value_component

    reasoning = (
        f"沪深300由北向资金、宏观代理和位置因子投票，"
        f"北向={north_score:.2f}、宏观={macro_score:.2f}×{weight_multiplier:.1f}。"
    )
    return result(
        index_code="000300.SH",
        index_name="沪深300",
        trade_date=trade_date,
        predict_for_trade_date=predict_for_trade_date,
        score=score,
        signals={
            "northbound_intraday_score": round(north_score, 6),
            "macro_proxy_score": round(macro_score, 6),
            "macro_weight_multiplier": round(weight_multiplier, 4),
            "valuation_proxy_percentile": round(valuation_pct, 4),
            "value_component": round(value_component, 6),
        },
        reasoning=reasoning,
        model_family="rule_v1",
        degraded_reasons=reasons,
    )
