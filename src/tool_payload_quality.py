"""
Helpers for data plugin payloads (quality_score, freshness hints).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

_POLICY: Optional[Dict[str, Any]] = None


def _load_policy() -> Dict[str, Any]:
    global _POLICY
    if _POLICY is not None:
        return _POLICY
    root = Path(__file__).resolve().parents[1]
    p = root / "config" / "data_quality_policy.yaml"
    if not p.is_file():
        _POLICY = {}
        return _POLICY
    try:
        _POLICY = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        _POLICY = {}
    return _POLICY


def effective_quality_score(payload: Optional[Dict[str, Any]]) -> Tuple[int, bool]:
    """
    Returns (score, is_default_missing).
    When quality_score is absent, use default_when_missing from policy (plan: 75).
    """
    pol = (_load_policy().get("quality_score") or {}) if isinstance(_load_policy(), dict) else {}
    default_missing = int(pol.get("default_when_missing", 75))
    if not isinstance(payload, dict):
        return default_missing, True
    qs = payload.get("quality_score")
    if qs is None:
        logger.info("tool_payload_quality: %s", pol.get("log_missing_as", "quality_score_missing"))
        return default_missing, True
    try:
        v = int(qs)
    except (TypeError, ValueError):
        return default_missing, True
    return max(0, min(100, v)), False


def quality_warn_message(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    pol = (_load_policy().get("quality_score") or {}) if isinstance(_load_policy(), dict) else {}
    thr = int(pol.get("warn_below", 70))
    score, _missing = effective_quality_score(payload if isinstance(payload, dict) else None)
    if score < thr:
        return f"数据质量分偏低（{score}），结论宜谨慎。"
    return None


def fused_confidence_hint(
    *,
    sentiment_dispersion: Optional[float] = None,
    quality_score: Optional[int] = None,
    technical_score: Optional[float] = None,
) -> Dict[str, Any]:
    """Lightweight fusion for reporting (deterministic, no ML)."""
    pol = (_load_policy().get("signal_fusion") or {}).get("weights") or {}
    wq = float(pol.get("quality_score", 0.35))
    wt = float(pol.get("technical_strength", 0.40))
    wd = float(pol.get("sentiment_dispersion_penalty", 0.25))

    q = (quality_score or 75) / 100.0
    t = max(0.0, min(1.0, (technical_score or 50.0) / 100.0))
    d = sentiment_dispersion
    if d is None:
        d_pen = 0.5
    else:
        d_pen = max(0.0, 1.0 - min(float(d) / 40.0, 1.0))

    fused = wq * q + wt * t + wd * d_pen
    return {
        "fused_confidence": round(max(0.0, min(1.0, fused)), 4),
        "inputs": {"quality": q, "technical": t, "dispersion_penalty": d_pen},
        "weights_used": {"quality_score": wq, "technical_strength": wt, "sentiment_dispersion_penalty": wd},
    }
