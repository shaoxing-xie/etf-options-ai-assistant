"""Chart Console screening_reader 单测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.chart_console.api.screening_reader import (
    ScreeningReader,
    list_screening_date_files,
    screening_artifact_path,
    validate_screening_date_key,
)


def test_validate_screening_date_key() -> None:
    assert validate_screening_date_key("2026-04-20") is True
    assert validate_screening_date_key("2026-13-01") is False
    assert validate_screening_date_key("not-a-date") is False
    assert validate_screening_date_key("") is False


def test_screening_artifact_path_safe() -> None:
    base = Path("/tmp/screening_test")
    p = screening_artifact_path(base, "2026-01-15")
    assert p is not None
    assert p.name == "2026-01-15.json"
    assert screening_artifact_path(base, "../evil") is None


def test_list_screening_date_files_orders_and_skips_emergency(tmp_path: Path) -> None:
    d = tmp_path / "screening"
    d.mkdir()
    (d / "2026-04-19.json").write_text("{}", encoding="utf-8")
    (d / "2026-04-20.json").write_text("{}", encoding="utf-8")
    (d / "emergency_pause.json").write_text("{}", encoding="utf-8")
    (d / "foo.json").write_text("{}", encoding="utf-8")
    assert list_screening_date_files(d) == ["2026-04-19", "2026-04-20"]


def test_screening_reader_summary_minimal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ScreeningReader, "effective_pause", lambda self: {"blocked": False, "reason": None, "weekly_regime_pause": False, "emergency_pause_active": False})
    root = tmp_path
    (root / "data" / "screening").mkdir(parents=True)
    (root / "data" / "watchlist").mkdir(parents=True)
    (root / "data" / "watchlist" / "default.json").write_text(
        '{"version":1,"symbols":["600000"],"meta":{}}',
        encoding="utf-8",
    )
    (root / "config").mkdir(parents=True)
    (root / "config" / "data_quality_policy.yaml").write_text(
        "screening:\n  min_quality_score: 55\n",
        encoding="utf-8",
    )
    art = {
        "run_date": "2026-04-20",
        "pause_active": False,
        "merged_watchlist_path": str(root / "wl.json"),
        "screening": {
            "success": True,
            "data": [{"symbol": "600000", "score": 80.0}],
            "quality_score": 90.0,
        },
    }
    (root / "data" / "screening" / "2026-04-20.json").write_text(json.dumps(art), encoding="utf-8")

    r = ScreeningReader(root)
    s = r.summary()
    assert s["latest_screening_date"] == "2026-04-20"
    assert len(s["latest_screening_rows"]) == 1
    assert s["latest_screening_rows"][0]["symbol"] == "600000"
    assert s["screening_policy"].get("min_quality_score") == 55
    rs = s.get("run_snapshot") or {}
    assert rs.get("quality_score") == 90.0
    assert rs.get("watchlist_merged") is True


def test_read_artifact_by_date_missing(tmp_path: Path) -> None:
    r = ScreeningReader(tmp_path)
    (tmp_path / "data" / "screening").mkdir(parents=True)
    assert r.read_artifact_by_date("2026-05-01") is None


def test_weekly_review_and_sentiment_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ScreeningReader, "effective_pause", lambda self: {"blocked": False, "reason": None, "weekly_regime_pause": False, "emergency_pause_active": False})
    root = tmp_path
    (root / "data" / "screening").mkdir(parents=True)
    (root / "data" / "watchlist").mkdir(parents=True)
    (root / "data" / "watchlist" / "default.json").write_text("{}", encoding="utf-8")
    (root / "config").mkdir(parents=True)
    (root / "config" / "data_quality_policy.yaml").write_text("screening: {}\n", encoding="utf-8")
    (root / "config" / "weekly_calibration.json").write_text(
        '{"regime":"oscillation","overall_score": 70}',
        encoding="utf-8",
    )
    (root / "data" / "screening" / "sentiment_context.json").write_text(
        '{"sentiment_stage":"test","overall_score": 71}',
        encoding="utf-8",
    )
    (root / "data" / "screening" / "weekly_review.json").write_text(
        '{"version": 1, "metrics": {"hit_rate_5d_pct": 0.4}}',
        encoding="utf-8",
    )

    r = ScreeningReader(root)
    s = r.summary()
    assert s["weekly_review"] is not None
    assert s["weekly_review"]["metrics"]["hit_rate_5d_pct"] == 0.4
    assert s["sentiment_snapshot"]["overall_score"] == 71
    assert s["sentiment_snapshot"]["sentiment_stage"] == "test"


def test_sentiment_snapshot_from_precheck_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Chart Console「市场情绪」应读取 pre-market 落盘的 data/sentiment_check/YYYY-MM-DD.json。"""
    monkeypatch.setattr(ScreeningReader, "effective_pause", lambda self: {"blocked": False, "reason": None, "weekly_regime_pause": False, "emergency_pause_active": False})
    root = tmp_path
    (root / "data" / "screening").mkdir(parents=True)
    (root / "data" / "watchlist").mkdir(parents=True)
    (root / "data" / "watchlist" / "default.json").write_text("{}", encoding="utf-8")
    (root / "config").mkdir(parents=True)
    (root / "config" / "data_quality_policy.yaml").write_text("screening: {}\n", encoding="utf-8")
    (root / "data" / "sentiment_check").mkdir(parents=True)
    (root / "data" / "sentiment_check" / "2026-04-20.json").write_text(
        json.dumps(
            {
                "overall_score": 68.2,
                "sentiment_stage": "偏多",
                "degraded": True,
            }
        ),
        encoding="utf-8",
    )

    r = ScreeningReader(root)
    s = r.summary()
    snap = s["sentiment_snapshot"]
    assert snap["overall_score"] == 68.2
    assert snap["sentiment_stage"] == "偏多"
    assert snap["degraded"] is True
    assert snap["precheck_date"] == "2026-04-20"
    assert "data/sentiment_check/2026-04-20.json" in snap.get("note", "")
