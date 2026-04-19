"""screening 收尾与熔断工具单测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.screening_gate_files as sgf
import src.screening_ops as ops
import src.watchlist_storage as ws


def test_finalize_screening_writes_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "watchlist_dir", lambda: tmp_path)
    monkeypatch.setattr(sgf, "screening_data_dir", lambda: tmp_path)

    payload = {
        "success": True,
        "data": [{"symbol": "600000", "score": 80.0, "factors": {"reversal_5d": {"raw": -1, "score": 70}}}],
        "quality_score": 90.0,
        "degraded": False,
        "config_hash": "abcd1234efgh5678",
        "elapsed_ms": 10,
        "plugin_version": "0.5.3",
    }
    r = ops.tool_finalize_screening_nightly(screening_result=payload, run_date="2026-04-20", attempt_watchlist=True)
    assert r.get("success")
    assert r.get("artifact_path")
    p = Path(r["artifact_path"])
    assert p.is_file()
    j = json.loads(p.read_text(encoding="utf-8"))
    assert j["screening"]["success"] is True


def test_emergency_pause_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.screening_gate_files.screening_data_dir", lambda: tmp_path)
    r = ops.tool_set_screening_emergency_pause(active=True, reason="test", until="2099-12-31")
    assert r.get("success")
    assert (tmp_path / "emergency_pause.json").is_file()
