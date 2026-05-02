from __future__ import annotations

from typing import Any, Dict, List

from .common import result, safe_float


def predict_csi500(index_features: Dict[str, Any], *, trade_date: str, predict_for_trade_date: str) -> Dict[str, Any]:
    reasons: List[str] = []
    sectors = index_features.get("sw_level1_top_sectors") if isinstance(index_features.get("sw_level1_top_sectors"), list) else []
    ret10 = safe_float(index_features.get("ret10"))
    limit_signal_proxy = safe_float(index_features.get("limit_signal_proxy"))

    if not sectors:
        reasons.append("missing_sw_level1_sector_snapshot")
    if ret10 is None:
        reasons.append("missing_ret10")
        ret10 = 0.0
    if limit_signal_proxy is None:
        reasons.append("missing_limit_signal_proxy")
        limit_signal_proxy = 0.0

    top_scores = [safe_float(r.get("ret10_proxy")) or 0.0 for r in sectors[:5]]
    industry_momentum = (sum(top_scores) / len(top_scores)) if top_scores else 0.0
    if limit_signal_proxy >= 70:
        limit_signal = -0.08
    elif limit_signal_proxy >= 40:
        limit_signal = -0.04
    elif limit_signal_proxy <= 10:
        limit_signal = 0.04
    else:
        limit_signal = 0.0
    index_momentum = 0.10 if ret10 > 0.03 else -0.05 if ret10 < -0.03 else 0.0

    score = industry_momentum * 0.5 + limit_signal * 0.3 + index_momentum * 0.2
    reasoning = (
        f"中证500采用申万一级行业传导，行业动量={industry_momentum:.2%}，"
        f"涨停热度代理={limit_signal_proxy:.0f}。"
    )
    return result(
        index_code="000905.SH",
        index_name="中证500",
        trade_date=trade_date,
        predict_for_trade_date=predict_for_trade_date,
        score=score,
        signals={
            "industry_momentum": round(industry_momentum, 6),
            "limit_signal": round(limit_signal, 6),
            "index_momentum": round(index_momentum, 6),
            "top_sectors": sectors[:5],
        },
        reasoning=reasoning,
        model_family="rule_v1",
        degraded_reasons=reasons,
    )
