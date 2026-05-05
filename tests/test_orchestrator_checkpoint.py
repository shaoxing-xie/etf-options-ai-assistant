"""CheckpointStore 与 context 过滤。"""

from __future__ import annotations

from pathlib import Path

from src.orchestrator.checkpoint_store import CheckpointStore, filter_checkpoint_context


def test_checkpoint_roundtrip_and_clear(tmp_path: Path):
    store = CheckpointStore(tmp_path, ttl_hours=24.0)
    store.save(
        "mytask",
        "2026-05-05",
        run_id="or_abc",
        next_step_id="step2",
        ctx_snapshot={"memory_injection": "x"},
    )
    cp = store.load("mytask", "2026-05-05")
    assert cp is not None
    assert cp.next_step_id == "step2"
    assert cp.ctx_snapshot.get("memory_injection") == "x"
    store.clear("mytask", "2026-05-05")
    assert store.load("mytask", "2026-05-05") is None


def test_filter_checkpoint_context_allowlist():
    ctx = {
        "memory_injection": "hi",
        "last_l4_result": {"a": 1},
        "noise": object(),
        "step_results": {"s1": {"step_id": "s1", "ok": True, "output": {"success": True}}},
    }
    out = filter_checkpoint_context(ctx, ("memory_injection", "last_l4_result", "step_results"))
    assert "memory_injection" in out
    assert "noise" not in out
    assert "step_results" in out
