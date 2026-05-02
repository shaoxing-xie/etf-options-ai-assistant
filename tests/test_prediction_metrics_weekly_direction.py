import json

from scripts import prediction_metrics_weekly as mod


def test_load_verified_hits_supports_index_direction(tmp_path, monkeypatch) -> None:
    pred_dir = tmp_path / "prediction_records"
    pred_dir.mkdir(parents=True)
    (pred_dir / "predictions_20260428.json").write_text(
        json.dumps(
            [
                {
                    "prediction_type": "index_direction",
                    "symbol": "000852.SH",
                    "target_date": "2026-04-29",
                    "prediction": {
                        "method": "kronos_local_logit_v1",
                        "direction": "up",
                        "probability": 63.0,
                        "quality_status": "ok",
                    },
                    "direction_verification": {"hit": True, "actual_direction": "up"},
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "PRED_DIR", pred_dir)

    rows = mod.load_verified_hits(["20260428"])

    assert len(rows) == 1
    assert rows[0]["date"] == "20260429"
    assert rows[0]["symbol"] == "000852.SH"
    assert rows[0]["hit"] is True
    assert rows[0]["prob_up"] == 0.63


def test_direction_metric_helpers() -> None:
    rows = [
        {"hit": True, "prob_up": 0.7, "actual_up": 1.0, "quality_status": "ok", "signal_strength": 0.4},
        {"hit": False, "prob_up": 0.4, "actual_up": 1.0, "quality_status": "degraded", "signal_strength": 0.2},
    ]

    assert mod.hit_rate(rows) == 0.5
    assert round(mod.brier_score(rows), 4) == 0.225
    assert mod.degraded_ratio(rows) == 0.5
    assert round(mod.signal_concentration(rows), 4) == 0.3
    assert round(mod.calibration_error(rows), 4) >= 0.0
