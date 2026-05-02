"""Tests for scripts/run_quality_backstop_audit_cli.py summary builder."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_cli():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "run_quality_backstop_audit_cli.py"
    spec = importlib.util.spec_from_file_location("run_quality_backstop_audit_cli", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_summary_team_ok_no_alerts() -> None:
    mod = _load_cli()
    report = {
        "results": [
            {
                "dataset": "sentiment_snapshot",
                "trade_date": "2026-04-28",
                "status": "ok",
                "degraded_streak": 0,
                "stale": False,
                "failure_stage": "",
                "reason": "",
            }
        ],
        "alerts_emitted": [],
    }
    rp = Path("/tmp/semantic_quality_2026-04-28.json")
    title, body = mod.build_summary_lines(report, rp)
    assert title == "质量兜底巡检（定时）"
    assert "TEAM_RESULT=TEAM_OK" in body
    assert "FAILURE_CODES=NONE" in body
    assert str(rp) in body


def test_backstop_kv_matches_summary_gate() -> None:
    mod = _load_cli()
    report = {
        "results": [{"dataset": "x", "trade_date": "2026-04-28", "status": "ok"}],
        "alerts_emitted": [],
    }
    kv = mod.backstop_kv_from_report(report, Path("/r.json"))
    assert kv["TEAM_RESULT"] == "TEAM_OK"
    assert kv["RISK"] == "LOW"
    assert kv["AUTOFIX_ALLOWED"] == "true"


def test_build_summary_team_fail_with_alerts() -> None:
    mod = _load_cli()
    report = {
        "results": [
            {
                "dataset": "ops_events",
                "trade_date": "2026-04-28",
                "status": "error",
                "degraded_streak": 0,
                "stale": False,
                "failure_stage": "snapshot",
                "reason": "snapshot_missing",
            }
        ],
        "alerts_emitted": [
            {
                "dataset": "ops_events",
                "trade_date": "2026-04-28",
                "status": "error",
                "reason": "snapshot_missing",
            }
        ],
    }
    title, body = mod.build_summary_lines(report, Path("/evidence.json"))
    assert "TEAM_RESULT=TEAM_FAIL" in body
    assert "RISK=HIGH" in body
    assert "ops_events" in body


def test_build_summary_includes_baseline_section() -> None:
    mod = _load_cli()
    report = {
        "results": [
            {
                "dataset": "sentiment_snapshot",
                "trade_date": "2026-04-28",
                "status": "ok",
            }
        ],
        "alerts_emitted": [],
    }
    _, body = mod.build_summary_lines(report, Path("/tmp/semantic_quality_2026-04-28.json"))
    assert "基线对比（cron 运行）" in body
    assert "今日 success=" in body


def test_build_summary_includes_baseline_stability_or_alert_line() -> None:
    mod = _load_cli()
    report = {
        "results": [{"dataset": "x", "trade_date": "2026-04-28", "status": "ok"}],
        "alerts_emitted": [],
    }
    _, body = mod.build_summary_lines(report, Path("/tmp/semantic_quality_2026-04-28.json"))
    assert ("运行基线稳定" in body) or ("运行基线出现劣化" in body)
