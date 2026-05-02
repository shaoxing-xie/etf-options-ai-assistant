import json

from scripts import verify_predictions as mod


def test_verify_direction_predictions_for_target_date(tmp_path, monkeypatch) -> None:
    pred_dir = tmp_path / "prediction_records"
    pred_dir.mkdir(parents=True)
    record_path = pred_dir / "predictions_20260428.json"
    record_path.write_text(
        json.dumps(
            [
                {
                    "prediction_type": "index_direction",
                    "symbol": "000688.SH",
                    "target_date": "20260429",
                    "metadata": {"trade_date": "2026-04-28"},
                    "prediction": {"direction": "up", "probability": 61.0},
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "PREDICTION_RECORDS_DIR", pred_dir)

    def _close(symbol: str, date: str):
        return {"20260428": 100.0, "20260429": 101.0}[date]

    monkeypatch.setattr(mod, "_load_index_daily_close", _close)

    stats = mod.verify_direction_predictions_for_target_date("20260429")
    saved = json.loads(record_path.read_text(encoding="utf-8"))

    assert stats["verified"] == 1
    assert stats["hit"] == 1
    assert saved[0]["direction_verified"] is True
    assert saved[0]["direction_verification"]["actual_direction"] == "up"
