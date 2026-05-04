"""Chart services：task_runs_v1 读取与 summary（monkeypatch ROOT）。"""

from __future__ import annotations

import json
from pathlib import Path

import apps.chart_console.api.services as services_mod
from apps.chart_console.api.services import ApiServices


def test_get_orchestrator_task_runs_with_summary(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    day_dir = root / "data" / "semantic" / "task_runs_v1" / "2026_04_30"
    day_dir.mkdir(parents=True)
    doc = {
        "schema_name": "task_run_record_v1",
        "schema_version": "1.0.0",
        "trade_date": "2026-04-30",
        "run_id": "or_test123",
        "payload": {
            "task_id": "daily_health",
            "trade_date": "2026-04-30",
            "steps": [{"step_id": "a", "ok": True}, {"step_id": "b", "ok": True}],
        },
    }
    (day_dir / "or_test123.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(services_mod, "ROOT", root)
    svc = ApiServices()
    out = svc.get_orchestrator_task_runs("2026-04-30", limit=10)
    assert out.get("success") is True
    data = out.get("data") or {}
    assert len(data.get("runs") or []) == 1
    summary = data.get("summary") or {}
    assert summary.get("run_count") == 1
    assert summary.get("step_ok_ratio_avg") == 1.0
    assert "daily_health" in (summary.get("unique_task_ids") or [])
