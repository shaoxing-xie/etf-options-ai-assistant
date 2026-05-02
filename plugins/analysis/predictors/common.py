from __future__ import annotations

from typing import Any, Dict, List, Optional


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def score_to_probability(score: float, *, base: float = 50.0, scale: float = 100.0, lo: float = 35.0, hi: float = 80.0) -> float:
    return clamp(base + score * scale, lo, hi)


def confidence_from_score(score: float, degraded: bool = False) -> str:
    mag = abs(float(score))
    if degraded:
        return "low"
    if mag >= 0.35:
        return "high"
    if mag >= 0.15:
        return "medium"
    return "low"


def classify_quality_reason(reason: str) -> str:
    token = str(reason or "").strip().lower()
    if not token:
        return "info"
    if any(
        key in token
        for key in (
            "runtime_failed",
            "import_failed",
            "artifact_missing",
            "snapshot_missing",
            "prediction_build_failed",
            "semantic_missing",
        )
    ):
        return "failed"
    return "degraded"


def quality_status_from_reasons(reasons: List[str]) -> str:
    if not reasons:
        return "info"
    if any(classify_quality_reason(reason) == "failed" for reason in reasons):
        return "failed"
    return "degraded"


def result(
    *,
    index_code: str,
    index_name: str,
    trade_date: str,
    predict_for_trade_date: str,
    score: float,
    signals: Dict[str, Any],
    reasoning: str,
    model_family: str,
    degraded_reasons: Optional[List[str]] = None,
) -> Dict[str, Any]:
    reasons = list(degraded_reasons or [])
    probability = score_to_probability(score)
    direction = "up" if probability > 55 else "down" if probability < 45 else "neutral"
    if direction == "down":
        probability = 100.0 - probability
    return {
        "index_code": index_code,
        "index_name": index_name,
        "trade_date": trade_date,
        "predict_for_trade_date": predict_for_trade_date,
        "direction": direction,
        "probability": round(probability, 2),
        "confidence": confidence_from_score(score, degraded=bool(reasons)),
        "signals": signals,
        "score_breakdown": {"total_score": round(float(score), 6)},
        "reasoning": reasoning,
        "quality_status": quality_status_from_reasons(reasons),
        "degraded_reason": ",".join(reasons) if reasons else None,
        "model_family": model_family,
    }
