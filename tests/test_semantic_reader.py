from __future__ import annotations

import json
from pathlib import Path

from apps.chart_console.api.semantic_reader import SemanticReader


def test_semantic_dashboard_and_timeline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.chart_console.api.screening_reader.ScreeningReader.effective_pause",
        lambda self: {"blocked": False, "reason": None, "weekly_regime_pause": False, "emergency_pause_active": False},
    )
    root = tmp_path
    (root / "data" / "screening").mkdir(parents=True)
    (root / "data" / "watchlist").mkdir(parents=True)
    (root / "data" / "tail_screening").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "data" / "watchlist" / "default.json").write_text('{"symbols":["000001"]}', encoding="utf-8")
    (root / "config" / "weekly_calibration.json").write_text('{"regime":"oscillation"}', encoding="utf-8")
    (root / "config" / "data_quality_policy.yaml").write_text("screening: {}\n", encoding="utf-8")
    (root / "data" / "screening" / "2026-04-22.json").write_text(
        json.dumps({"run_date": "2026-04-22", "screening": {"data": [{"symbol": "000001", "score": 80}]}}),
        encoding="utf-8",
    )
    (root / "data" / "tail_screening" / "latest.json").write_text(
        json.dumps({"run_date": "2026-04-22", "recommended": [{"symbol": "000001", "score": 88}]}),
        encoding="utf-8",
    )
    (root / "data" / "semantic" / "timeline_feed").mkdir(parents=True)
    (root / "data" / "semantic" / "timeline_feed" / "2026-04-22.jsonl").write_text(
        json.dumps({"_meta": {"task_id": "intraday-tail-screening", "quality_status": "ok", "lineage_refs": []}, "data": {"event_id": "e1", "event_time": "2026-04-22T14:00:00Z", "event_type": "tail", "summary": "ok"}})
        + "\n",
        encoding="utf-8",
    )

    reader = SemanticReader(root)
    dashboard = reader.dashboard()
    assert "sentiment_temperature" in dashboard
    assert dashboard["top_recommendations"][0]["symbol"] == "000001"
    timeline = reader.timeline("2026-04-22")
    assert timeline["events"][0]["event_id"] == "e1"


def test_semantic_ops_events_view(monkeypatch, tmp_path: Path) -> None:
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "a1",
                        "name": "send report",
                        "enabled": True,
                        "schedule": {"expr": "0 9 * * 1-5"},
                        "payload": {"toolsAllow": ["tool_send_x"]},
                        "state": {"lastRunStatus": "ok", "consecutiveErrors": 0},
                    },
                    {
                        "id": "b1",
                        "name": "collect data",
                        "enabled": True,
                        "schedule": {"expr": "*/5 9-15 * * 1-5"},
                        "payload": {"toolsAllow": ["tool_run_data_cache_job"]},
                        "state": {"lastRunStatus": "error", "consecutiveErrors": 2},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "apps.chart_console.api.semantic_reader.Path",
        lambda p: jobs_path if str(p) == "/home/xie/.openclaw/cron/jobs.json" else Path(p),
    )
    reader = SemanticReader(tmp_path)
    payload = reader.ops_events()
    assert payload["_meta"]["schema_name"] == "ops_events_view_v1"
    assert len(payload["execution_audit_events"]) == 1
    assert len(payload["collection_quality_events"]) == 1
    assert payload["collection_quality_events"][0]["quality_status"] == "degraded"


def test_semantic_ops_events_prefers_snapshot(tmp_path: Path) -> None:
    root = tmp_path
    d = root / "data" / "semantic" / "ops_events"
    d.mkdir(parents=True)
    snap = {
        "_meta": {"schema_name": "ops_events_view_v1", "trade_date": "2026-04-22"},
        "data": {"execution_audit_events": [{"task_id": "snap"}], "collection_quality_events": []},
    }
    (d / "2026-04-22.json").write_text(json.dumps(snap), encoding="utf-8")
    reader = SemanticReader(root)
    payload = reader.ops_events("2026-04-22")
    assert payload["execution_audit_events"][0]["task_id"] == "snap"


def test_semantic_screening_view_prefers_snapshot(tmp_path: Path) -> None:
    root = tmp_path
    d = root / "data" / "semantic" / "screening_view"
    d.mkdir(parents=True)
    snap = {
        "_meta": {"schema_name": "screening_view_v1", "trade_date": "2026-04-22"},
        "data": {
            "candidates": {"nightly": [{"symbol": "000001"}], "tail": []},
            "task_execution_monitor": [],
            "watchlist_state": {},
            "performance_context": {},
            "effect_stats": {},
            "sector_rotation_heatmap": [],
            "tail_paradigm_pools": {},
            "alert_thresholds": {},
        },
    }
    (d / "2026-04-22.json").write_text(json.dumps(snap), encoding="utf-8")
    reader = SemanticReader(root)
    payload = reader.screening_view("2026-04-22")
    assert payload["candidates"]["nightly"][0]["symbol"] == "000001"


def test_semantic_screening_candidates_prefers_snapshot(tmp_path: Path) -> None:
    root = tmp_path
    d = root / "data" / "semantic" / "screening_candidates"
    d.mkdir(parents=True)
    snap = {
        "_meta": {"schema_name": "screening_candidates_v1", "trade_date": "2026-04-22"},
        "data": {"run_date": "2026-04-22", "candidates": [{"symbol": "000001"}], "summary": {}, "artifact_ref": "x"},
    }
    (d / "2026-04-22.json").write_text(json.dumps(snap), encoding="utf-8")
    reader = SemanticReader(root)
    payload = reader.screening_candidates("2026-04-22")
    assert payload["candidates"][0]["symbol"] == "000001"
