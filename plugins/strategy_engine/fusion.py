"""
Fusion v1 / v1.1 / v1.2 — 加权、一致性、强冲突降级。
"""

from __future__ import annotations

import copy
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from strategy_engine.schemas import FusionResult, SignalCandidate

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_fusion_config(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or (_project_root() / "config" / "strategy_fusion.yaml")
    if not p.exists():
        return {
            "version": "1.0",
            "policy": {
                "score_threshold": 0.2,
                "agree_ratio_min": 0.6,
                "strong_abs_score": 0.65,
            },
            "strategy_weights": {
                "src_signal_generation": 0.5,
                "etf_trend_following": 0.5,
            },
            "providers": {"src_signal_generation": True, "etf_trend_following": True, "llm": False},
        }
    text = p.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text) or {}
    raise RuntimeError("PyYAML required to load strategy_fusion.yaml")


def merge_weights(
    yaml_weights: Dict[str, float],
    dynamic: Optional[Dict[str, float]],
) -> Dict[str, float]:
    out = copy.deepcopy(yaml_weights)
    if isinstance(dynamic, dict):
        for k, v in dynamic.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    return out


def fuse_for_symbol(
    candidates: List[SignalCandidate],
    weights: Dict[str, float],
    policy: Dict[str, float],
) -> Optional[FusionResult]:
    """
    对同一 symbol 的一组候选做融合。
    policy keys: score_threshold, agree_ratio_min, strong_abs_score
    """
    if not candidates:
        return None

    sym = candidates[0].symbol
    thr = float(policy.get("score_threshold", 0.2))
    agree_min = float(policy.get("agree_ratio_min", 0.6))
    strong = float(policy.get("strong_abs_score", 0.65))

    wsum = 0.0
    acc = 0.0
    for c in candidates:
        w = float(weights.get(c.strategy_id, 0.1))
        wsum += w
        acc += c.score * c.confidence * w
    if wsum <= 0:
        final_score = 0.0
    else:
        final_score = acc / wsum

    long_n = sum(1 for c in candidates if c.direction == "long")
    short_n = sum(1 for c in candidates if c.direction == "short")
    neu_n = sum(1 for c in candidates if c.direction == "neutral")
    n = len(candidates)
    dominant = "neutral"
    if long_n >= short_n and long_n >= neu_n:
        dominant = "long"
    elif short_n >= long_n and short_n >= neu_n:
        dominant = "short"

    same_ratio = max(long_n, short_n, neu_n) / n if n else 0.0

    strong_long = any(c.direction == "long" and c.score >= strong for c in candidates)
    strong_short = any(c.direction == "short" and c.score <= -strong for c in candidates)

    rationale_refs = [f"{c.strategy_id}: dir={c.direction} score={c.score:.3f} conf={c.confidence:.2f}" for c in candidates]
    meta: Dict[str, Any] = {
        "final_score_raw": final_score,
        "same_direction_ratio": same_ratio,
        "counts": {"long": long_n, "short": short_n, "neutral": neu_n},
    }

    # v1.2 强冲突
    if strong_long and strong_short:
        return FusionResult(
            strategy_id="ensemble_fused",
            symbol=sym,
            direction="neutral",
            score=0.0,
            confidence=min(1.0, abs(final_score)),
            rationale="强多强空并存，降级观望（v1.2）",
            rationale_refs=rationale_refs + ["v1.2_conflict"],
            metadata={**meta, "rule": "v1.2"},
        )

    # v1.1 一致性
    if same_ratio < agree_min:
        return FusionResult(
            strategy_id="ensemble_fused",
            symbol=sym,
            direction="neutral",
            score=0.0,
            confidence=min(1.0, abs(final_score)),
            rationale=f"一致性不足（{same_ratio:.2f} < {agree_min}），观望（v1.1）",
            rationale_refs=rationale_refs + ["v1.1_agree"],
            metadata={**meta, "rule": "v1.1"},
        )

    # v1 阈值
    if abs(final_score) < thr:
        direction = "neutral"
    elif final_score > 0:
        direction = "long"
    else:
        direction = "short"

    if direction == "neutral":
        return FusionResult(
            strategy_id="ensemble_fused",
            symbol=sym,
            direction="neutral",
            score=float(final_score),
            confidence=min(1.0, abs(final_score)),
            rationale=f"加权分 |{final_score:.3f}| < {thr}，观望（v1）",
            rationale_refs=rationale_refs + ["v1_threshold"],
            metadata={**meta, "rule": "v1"},
        )

    return FusionResult(
        strategy_id="ensemble_fused",
        symbol=sym,
        direction=direction,
        score=float(final_score),
        confidence=min(1.0, abs(final_score)),
        rationale=f"融合方向={direction}，加权分={final_score:.3f}",
        rationale_refs=rationale_refs + ["v1_fused"],
        metadata={**meta, "rule": "v1", "dominant_vote": dominant},
    )


def fuse_all(
    candidates: List[SignalCandidate],
    weights: Dict[str, float],
    policy: Dict[str, float],
) -> Optional[FusionResult]:
    """按 symbol 分组；当前 v1 只支持单标的主融合（取第一组或合并单 symbol）。"""
    if not candidates:
        return None
    by_sym: Dict[str, List[SignalCandidate]] = defaultdict(list)
    for c in candidates:
        by_sym[c.symbol].append(c)
    # 若多 symbol，逐 symbol 融合返回第一个（v1）；后续可扩展多标的
    first_key = sorted(by_sym.keys())[0]
    return fuse_for_symbol(by_sym[first_key], weights, policy)
