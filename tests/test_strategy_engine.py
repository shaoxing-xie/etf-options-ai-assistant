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
    fuse_for_symbol,
    merge_weights,
)
from strategy_engine.schemas import FusionResult, SignalCandidate  # noqa: E402
from strategy_engine.tool_strategy_engine import _run_inputs_hash  # noqa: E402


def test_inputs_hash_stable() -> None:
    a = _run_inputs_hash({"b": 1, "a": 2})
    b = _run_inputs_hash({"a": 2, "b": 1})
    assert a == b
    assert len(a) == 64


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
