from __future__ import annotations

from pathlib import Path

import pytest

import src.watchlist_storage as ws
from src import screening_utils
from src.watchlist_storage import merge_screening_picks, read_watchlist


def test_validate_screening_response_ok() -> None:
    ok, issues = screening_utils.validate_screening_response(
        {
            "success": True,
            "data": [{"symbol": "600000", "score": 80.0, "factors": {"reversal_5d": {"raw": -1, "score": 70}}}],
            "quality_score": 90.0,
            "degraded": False,
            "config_hash": "abcd1234efgh5678",
            "elapsed_ms": 12,
            "plugin_version": "0.5.3",
        }
    )
    assert ok and issues == []


def test_merge_screening_picks_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "watchlist_dir", lambda: tmp_path)
    p = merge_screening_picks(
        {
            "success": True,
            "data": [{"symbol": "000001", "score": 1, "factors": {}}],
            "quality_score": 88.0,
            "degraded": False,
            "config_hash": "h1",
            "plugin_version": "0.5.3",
            "universe": "custom",
        }
    )
    assert p.parent == tmp_path
    cur = read_watchlist(p)
    assert cur["symbols"] == ["000001"]
    assert cur["meta"]["last_screening"]["config_hash"] == "h1"
