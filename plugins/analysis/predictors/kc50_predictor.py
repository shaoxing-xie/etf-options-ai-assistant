from __future__ import annotations

from typing import Any, Dict, List

from .common import clamp, result, safe_float


def predict_kc50(index_features: Dict[str, Any], *, trade_date: str, predict_for_trade_date: str) -> Dict[str, Any]:
    reasons: List[str] = []
    kronos_available = bool(index_features.get("kronos_available"))
    kronos_score = safe_float(index_features.get("kronos_score"))
    kronos_reason = str(index_features.get("degraded_reason") or "").strip()
    ret10 = safe_float(index_features.get("ret10"))
    limit_ratio = safe_float(index_features.get("limit_up_ratio_proxy"))
    sector_leadership = safe_float(index_features.get("sector_leadership_score"))

    if not kronos_available:
        if kronos_reason:
            reasons.append(kronos_reason)
        kronos_score = 0.0
    if ret10 is None:
        reasons.append("missing_ret10")
        ret10 = 0.0
    if limit_ratio is None:
        reasons.append("missing_kc50_limit_up_proxy")
        limit_ratio = 0.0
    if sector_leadership is None:
        sector_leadership = 0.0

    sentiment_score = -0.10 if limit_ratio > 0.12 else 0.05 if limit_ratio < 0.04 else 0.0
    momentum_score = 0.10 if ret10 > 0.03 else -0.10 if ret10 < -0.03 else 0.0
    leadership_score = clamp(sector_leadership, -0.2, 0.2)
    kronos_component = clamp(kronos_score or 0.0, -1.0, 1.0) * 0.4
    score = kronos_component + sentiment_score * 0.3 + momentum_score * 0.2 + leadership_score * 0.1

    reasoning = (
        f"科创50使用 {'Kronos+规则' if kronos_available else '规则主导'}，"
        f"情绪热度代理={limit_ratio:.2%}。"
    )
    return result(
        index_code="000688.SH",
        index_name="科创50",
        trade_date=trade_date,
        predict_for_trade_date=predict_for_trade_date,
        score=score,
        signals={
            "kronos_available": kronos_available,
            "kronos_score": round(float(kronos_score or 0.0), 6),
            "limit_up_ratio_proxy": round(limit_ratio, 6),
            "sentiment_score": round(sentiment_score, 6),
            "momentum_score": round(momentum_score, 6),
            "sector_leadership_score": round(leadership_score, 6),
        },
        reasoning=reasoning,
        model_family="rule_plus_kronos_v1" if kronos_available else "rule_v1",
        degraded_reasons=reasons,
    )
