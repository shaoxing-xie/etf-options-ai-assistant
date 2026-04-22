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
    assert len(payload["task_health_events"]) == 2
    assert any(x.get("quality_status") == "degraded" for x in payload["task_health_events"])
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


def test_research_metrics_and_diagnostics(tmp_path: Path) -> None:
    root = tmp_path
    (root / "data" / "semantic" / "screening_view").mkdir(parents=True)
    (root / "data" / "semantic" / "sentiment_snapshot").mkdir(parents=True)
    (root / "data" / "semantic" / "timeline_feed").mkdir(parents=True)
    (root / "data" / "screening").mkdir(parents=True)
    (root / "data" / "watchlist").mkdir(parents=True)
    (root / "data" / "tail_screening").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "config" / "weekly_calibration.json").write_text('{"regime":"oscillation"}', encoding="utf-8")
    (root / "config" / "data_quality_policy.yaml").write_text("screening: {}\n", encoding="utf-8")
    (root / "data" / "watchlist" / "default.json").write_text('{"symbols":[]}', encoding="utf-8")
    (root / "data" / "screening" / "2026-04-22.json").write_text(
        json.dumps({"run_date": "2026-04-22", "screening": {"data": [{"symbol": "000001", "score": 80}]}}),
        encoding="utf-8",
    )
    (root / "data" / "tail_screening" / "latest.json").write_text(
        json.dumps({"run_date": "2026-04-22", "recommended": [{"symbol": "000001", "score": 88}]}),
        encoding="utf-8",
    )
    (root / "data" / "semantic" / "screening_view" / "2026-04-22.json").write_text(
        json.dumps(
            {
                "_meta": {"schema_name": "screening_view_v1", "trade_date": "2026-04-22"},
                "data": {
                    "watchlist_state": {},
                    "candidates": {"nightly": [{"symbol": "000001", "score": 80}], "tail": [{"symbol": "000001", "score": 88}]},
                    "performance_context": {},
                    "effect_stats": {"hit_rate_5d_pct": 0.6, "pause_events_count": 0},
                    "sector_rotation_heatmap": [],
                    "tail_paradigm_pools": {},
                    "task_execution_monitor": [{"task_id": "t1", "status": "ok"}],
                    "alert_thresholds": {},
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "data" / "semantic" / "sentiment_snapshot" / "2026-04-22.json").write_text(
        json.dumps(
            {
                "_meta": {"schema_name": "sentiment_snapshot_v1", "trade_date": "2026-04-22"},
                "data": {"overall_score": 72, "sentiment_stage": "高潮期", "sentiment_dispersion": 0.42},
            }
        ),
        encoding="utf-8",
    )
    (root / "data" / "semantic" / "timeline_feed" / "2026-04-22.jsonl").write_text(
        json.dumps(
            {
                "_meta": {"task_id": "intraday-tail-screening", "quality_status": "degraded", "lineage_refs": []},
                "data": {
                    "event_id": "ev1",
                    "event_time": "2026-04-22T14:00:00Z",
                    "event_type": "tail_recommendation",
                    "summary": "degraded",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    reader = SemanticReader(root)
    metrics = reader.research_metrics("2026-04-22", window=5)
    assert metrics["_meta"]["schema_name"] == "research_metrics_v1"
    assert metrics["sentiment_trend"]["current_score"] == 72
    assert metrics["screening_effectiveness"]["nightly_candidates"] == 1
    diagnostics = reader.research_diagnostics("2026-04-22", window=5)
    assert diagnostics["_meta"]["schema_name"] == "research_diagnostics_v1"
    assert diagnostics["diagnostics"]["degraded_event_count"] >= 1
    factor = reader.factor_diagnostics("2026-04-22", period="week")
    assert factor["_meta"]["schema_name"] == "factor_diagnostics_v1"
    assert isinstance(factor["factors"], list)
    attribution = reader.strategy_attribution("2026-04-22")
    assert attribution["_meta"]["schema_name"] == "strategy_attribution_v1"
    assert "by_task_stage" in attribution["attribution"]


def test_orchestration_timeline_and_health(tmp_path: Path) -> None:
    root = tmp_path
    events_dir = root / "data" / "decisions" / "orchestration" / "events"
    events_dir.mkdir(parents=True)
    event_row = {
        "_meta": {"task_id": "nightly-stock-screening", "run_id": "r1", "quality_status": "ok"},
        "data": {
            "event_id": "nightly-stock-screening.r1.succeeded",
            "event_time": "2026-04-22T20:00:00Z",
            "task_id": "nightly-stock-screening",
            "run_id": "r1",
            "from_state": "running",
            "to_state": "succeeded",
            "reason": "completed",
            "trigger_source": "cron",
            "idempotency_key": "nightly-stock-screening:2026-04-22:daily",
        },
    }
    (events_dir / "2026-04-22.jsonl").write_text(json.dumps(event_row) + "\n", encoding="utf-8")
    (root / "data" / "semantic" / "screening_view").mkdir(parents=True)
    (root / "data" / "semantic" / "screening_view" / "2026-04-22.json").write_text(
        json.dumps({"_meta": {"schema_name": "screening_view_v1"}, "data": {"task_execution_monitor": []}}),
        encoding="utf-8",
    )
    reader = SemanticReader(root)
    timeline = reader.orchestration_timeline("2026-04-22")
    assert timeline["_meta"]["schema_name"] == "orchestration_timeline_v1"
    assert timeline["stats"]["succeeded_count"] == 1
    health = reader.task_dependency_health("2026-04-22")
    assert health["_meta"]["schema_name"] == "task_dependency_health_v1"
    assert "satisfaction_rate" in health["health_metrics"]
