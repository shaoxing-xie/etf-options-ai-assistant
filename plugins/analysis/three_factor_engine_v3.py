from __future__ import annotations

from typing import Any, Dict, List


def compute_three_factor_v3_candidates(
    ranked_payload: List[Dict[str, Any]],
    *,
    share_trend_weight: float = 0.15,
) -> Dict[str, Any]:
    """
    v3 scoring facade:
    momentum x leadership x breadth + capital resonance + sentiment gate.
    """
    out: List[Dict[str, Any]] = []
    risk_events: List[Dict[str, Any]] = []
    for row in ranked_payload:
        tf = row.get("three_factor") if isinstance(row.get("three_factor"), dict) else {}
        momentum = float(tf.get("momentum_score") or 0.0)
        gate = float(tf.get("environment_gate") or 1.0)
        sentiment = float(tf.get("sentiment_score") or 0.5)
        resonance = float(tf.get("capital_resonance_score") or 0.0)
        leadership = float(tf.get("leadership_score_proxy") or 0.5)
        breadth = float(tf.get("breadth_score_proxy") or 0.5)
        share = float(tf.get("share_trend_score_proxy") or resonance)
        composite = ((momentum * leadership * breadth) * 0.55) + (resonance * 0.2) + (share * share_trend_weight) + (sentiment * 0.1)
        composite = composite * gate
        row_out = dict(row)
        row_out["composite_score_v3"] = composite
        row_out["score_breakdown_v3"] = {
            "momentum": momentum,
            "leadership": leadership,
            "breadth": breadth,
            "capital_resonance": resonance,
            "share_trend": share,
            "sentiment": sentiment,
            "gate": gate,
        }
        out.append(row_out)
        if breadth < 0.35:
            risk_events.append(
                {
                    "event_type": "breadth_collapse_gate",
                    "severity": "high",
                    "symbol": row.get("symbol"),
                    "details": {"breadth_score_proxy": breadth},
                }
            )
        if share < 0 and momentum > 0:
            risk_events.append(
                {
                    "event_type": "price_share_divergence_gate",
                    "severity": "medium",
                    "symbol": row.get("symbol"),
                    "details": {"share_trend_score_proxy": share, "momentum_score": momentum},
                }
            )
    out.sort(key=lambda x: float(x.get("composite_score_v3") or 0.0), reverse=True)
    return {"candidates": out, "risk_events": risk_events}

