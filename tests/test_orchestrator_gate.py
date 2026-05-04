from __future__ import annotations

from src.orchestrator.gate import apply_l4_gate, resolve_l4_confidence


def test_resolve_l4_confidence_from_meta():
    d = {"_meta": {"confidence": 0.8}, "data": {}}
    assert resolve_l4_confidence(d) == 0.8


def test_resolve_l4_confidence_from_data():
    d = {"data": {"confidence": 0.5}}
    assert resolve_l4_confidence(d) == 0.5


def test_apply_l4_gate_pass():
    d = {"_meta": {"confidence": 0.8}}
    assert apply_l4_gate(d, {"min_confidence": 0.6, "on_fail": "block"}) == "pass"


def test_apply_l4_gate_block():
    d = {"_meta": {"confidence": 0.1}}
    assert apply_l4_gate(d, {"min_confidence": 0.6, "on_fail": "block"}) == "block"
