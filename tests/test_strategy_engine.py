"""
Unit tests for strategy_engine fusion and schema (no network).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins"))
sys.path.insert(0, str(ROOT))

from strategy_engine.fusion import (  # noqa: E402
    fuse_all,
    fuse_all_by_symbol,
    fuse_for_symbol,
    merge_weights,
)
from strategy_engine.schemas import SignalCandidate  # noqa: E402
from strategy_engine.llm_strategy import generate_llm_candidates  # noqa: E402
from strategy_engine.tool_strategy_engine import (  # noqa: E402
    _build_fusion_summary,
    _run_inputs_hash,
)


def test_inputs_hash_stable() -> None:
    a = _run_inputs_hash({"b": 1, "a": 2})
    b = _run_inputs_hash({"a": 2, "b": 1})
    assert a == b
    assert len(a) == 64


def test_inputs_hash_sensitivity_to_fusion_policy() -> None:
    base = {
        "engine_inputs_hash_schema": "1",
        "policy_version": "1.0",
        "fusion_policy": {
            "score_threshold": 0.2,
            "agree_ratio_min": 0.6,
            "strong_abs_score": 0.65,
        },
        "strategy_weights_yaml": {"etf_trend_following": 0.5, "src_signal_generation": 0.5},
        "underlyings": ["510300"],
        "index_codes": ["000300"],
        "mode": "production",
        "providers": ["src_signal_generation", "etf_trend_following"],
        "date": "2026-04-05",
    }
    alt = {**base, "fusion_policy": {**base["fusion_policy"], "agree_ratio_min": 0.5}}
    assert _run_inputs_hash(base) != _run_inputs_hash(alt)


def test_inputs_hash_sensitivity_to_strategy_weights_yaml() -> None:
    base = {
        "engine_inputs_hash_schema": "1",
        "policy_version": "1.0",
        "fusion_policy": {
            "score_threshold": 0.2,
            "agree_ratio_min": 0.6,
            "strong_abs_score": 0.65,
        },
        "strategy_weights_yaml": {"a": 0.5, "b": 0.5},
        "underlyings": ["510300"],
        "index_codes": ["000300"],
        "mode": "production",
        "providers": ["a", "b"],
        "date": "2026-04-05",
    }
    alt = {**base, "strategy_weights_yaml": {"a": 0.7, "b": 0.3}}
    assert _run_inputs_hash(base) != _run_inputs_hash(alt)


def test_build_fusion_summary() -> None:
    from strategy_engine.schemas import FusionResult  # noqa: E402

    policy = {"score_threshold": 0.2, "agree_ratio_min": 0.6, "strong_abs_score": 0.65}
    cands = [
        SignalCandidate("a", "510300", "long", 0.7, 1.0, inputs_hash="h"),
    ]
    fused = {
        "510300": FusionResult(
            strategy_id="ensemble_fused",
            symbol="510300",
            direction="long",
            score=0.7,
            confidence=0.7,
            rationale="ok",
        ),
        "510500": FusionResult(
            strategy_id="ensemble_fused",
            symbol="510500",
            direction="neutral",
            score=0.0,
            confidence=0.1,
            rationale="agree",
        ),
    }
    s = _build_fusion_summary(cands, fused, policy["strong_abs_score"])
    assert s["total_candidates"] == 1
    assert s["fused_symbol_count"] == 2
    assert s["non_neutral_fused_count"] == 1
    assert s["strong_fused_count"] == 1
    assert s["strong_abs_score_threshold"] == 0.65


def test_llm_candidates_require_providers_llm_flag() -> None:
    assert generate_llm_candidates({}) == []
    assert generate_llm_candidates({"providers_llm": False}) == []
    assert generate_llm_candidates({"providers_llm": True}) == []


def test_merge_weights_overrides() -> None:
    base = {"s1": 0.5, "s2": 0.5}
    dyn = {"s1": 0.8}
    m = merge_weights(base, dyn)
    assert m["s1"] == 0.8
    assert m["s2"] == 0.5


def test_fuse_v12_strong_conflict_neutral() -> None:
    policy = {"score_threshold": 0.05, "agree_ratio_min": 0.3, "strong_abs_score": 0.5}
    weights = {"a": 1.0, "b": 1.0}
    cands = [
        SignalCandidate(
            strategy_id="a",
            symbol="510300",
            direction="long",
            score=0.9,
            confidence=1.0,
            inputs_hash="x",
        ),
        SignalCandidate(
            strategy_id="b",
            symbol="510300",
            direction="short",
            score=-0.9,
            confidence=1.0,
            inputs_hash="x",
        ),
    ]
    out = fuse_for_symbol(cands, weights, policy)
    assert out is not None
    assert out.direction == "neutral"
    assert out.metadata.get("rule") == "v1.2"


def test_fuse_v11_low_agreement() -> None:
    policy = {"score_threshold": 0.01, "agree_ratio_min": 0.99, "strong_abs_score": 0.99}
    weights = {"a": 1.0, "b": 1.0, "c": 1.0}
    cands = [
        SignalCandidate("a", "510300", "long", 0.8, 1.0, inputs_hash="h"),
        SignalCandidate("b", "510300", "short", -0.7, 1.0, inputs_hash="h"),
        SignalCandidate("c", "510300", "neutral", 0.0, 0.5, inputs_hash="h"),
    ]
    out = fuse_for_symbol(cands, weights, policy)
    assert out is not None
    assert out.direction == "neutral"
    assert out.metadata.get("rule") == "v1.1"


def test_fuse_all_by_symbol_multi_etf() -> None:
    policy = {"score_threshold": 0.1, "agree_ratio_min": 0.4, "strong_abs_score": 0.95}
    weights = {"a": 1.0, "b": 1.0}
    cands = [
        SignalCandidate("a", "510300", "long", 0.6, 0.9, inputs_hash="h"),
        SignalCandidate("b", "510300", "long", 0.5, 0.8, inputs_hash="h"),
        SignalCandidate("a", "510500", "short", -0.55, 0.85, inputs_hash="h"),
        SignalCandidate("b", "510500", "short", -0.5, 0.8, inputs_hash="h"),
    ]
    m = fuse_all_by_symbol(cands, weights, policy)
    assert set(m.keys()) == {"510300", "510500"}
    assert m["510300"].direction == "long"
    assert m["510500"].direction == "short"
    primary = fuse_all(cands, weights, policy)
    assert primary is not None
    assert primary.symbol == "510300"


def test_fuse_v1_long() -> None:
    policy = {"score_threshold": 0.1, "agree_ratio_min": 0.4, "strong_abs_score": 0.95}
    weights = {"a": 1.0, "b": 1.0}
    cands = [
        SignalCandidate("a", "510300", "long", 0.6, 0.9, inputs_hash="h"),
        SignalCandidate("b", "510300", "long", 0.5, 0.8, inputs_hash="h"),
    ]
    out = fuse_for_symbol(cands, weights, policy)
    assert out is not None
    assert out.direction == "long"
    assert out.metadata.get("rule") == "v1"


def test_trend_following_entry_refs_rewrites_symbol_and_index() -> None:
    from strategy_engine.rule_adapters import _trend_following_entry_refs  # noqa: E402

    refs = _trend_following_entry_refs("510500", "000905")
    assert refs
    assert all("510300 与 000300" not in r for r in refs)
    assert any("510500" in r for r in refs)
    assert any("000905" in r for r in refs)


def test_direction_from_hold() -> None:
    assert SignalCandidate.direction_from_hold("hold") == "neutral"
    assert SignalCandidate.direction_from_hold("long") == "long"


def test_ml_strategy_not_implemented() -> None:
    from strategy_engine.llm_strategy import MLStrategy  # noqa: E402

    with pytest.raises(NotImplementedError):
        MLStrategy.generate({})


def test_get_strategy_weights_reads_persisted_fusion_file(tmp_path, monkeypatch) -> None:
    """openclaw 进化：落盘权重优先于均等分配。"""
    p = tmp_path / "strategy_fusion_effective_weights.json"
    p.write_text(
        json.dumps(
            {"weights": {"src_signal_generation": 0.7, "etf_trend_following": 0.3}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STRATEGY_FUSION_WEIGHTS_PATH", str(p))
    import importlib

    import plugins.analysis.strategy_weight_manager as swm

    importlib.reload(swm)
    r = swm.get_strategy_weights(strategies=["src_signal_generation", "etf_trend_following"])
    assert r.get("success") is True
    assert abs(r["data"]["src_signal_generation"] - 0.7) < 1e-9
    assert abs(r["data"]["etf_trend_following"] - 0.3) < 1e-9
