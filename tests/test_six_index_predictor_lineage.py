from pathlib import Path

from plugins.analysis.six_index_next_day_predictor import build_l4, persist_l3, persist_l4, predict_all
from plugins.analysis.predictors.shanghai_predictor import predict_shanghai


def _prediction(index_code: str) -> dict:
    return {
        "index_code": index_code,
        "index_name": index_code,
        "trade_date": "2026-04-28",
        "predict_for_trade_date": "2026-04-29",
        "direction": "up",
        "probability": 60.0,
        "confidence": "medium",
        "signals": {},
        "score_breakdown": {"total_score": 0.1},
        "reasoning": "ok",
        "quality_status": "info",
        "degraded_reason": None,
        "model_family": "rule_v1",
    }


def test_predict_all_preserves_feature_lineage(monkeypatch) -> None:
    monkeypatch.setattr("plugins.analysis.six_index_next_day_predictor.predict_shanghai", lambda *args, **kwargs: _prediction("000001.SH"))
    monkeypatch.setattr("plugins.analysis.six_index_next_day_predictor.predict_csi300", lambda *args, **kwargs: _prediction("000300.SH"))
    monkeypatch.setattr("plugins.analysis.six_index_next_day_predictor.predict_kc50", lambda *args, **kwargs: _prediction("000688.SH"))
    monkeypatch.setattr("plugins.analysis.six_index_next_day_predictor.predict_chinext", lambda *args, **kwargs: _prediction("399006.SZ"))
    monkeypatch.setattr("plugins.analysis.six_index_next_day_predictor.predict_csi500", lambda *args, **kwargs: _prediction("000905.SH"))
    monkeypatch.setattr("plugins.analysis.six_index_next_day_predictor.predict_csi1000", lambda *args, **kwargs: _prediction("000852.SH"))

    doc = predict_all(
        {
            "_meta": {"run_id": "r1", "lineage_refs": ["data/features/six_index_next_day/2026-04-28.json"]},
            "trade_date": "2026-04-28",
            "predict_for_trade_date": "2026-04-29",
            "indices": {},
        }
    )

    assert doc["_meta"]["lineage_refs"] == ["data/features/six_index_next_day/2026-04-28.json"]


def test_persist_l3_and_l4_append_lineage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("plugins.analysis.six_index_next_day_predictor.ROOT", tmp_path)
    l3_doc = {
        "_meta": {"lineage_refs": ["data/features/six_index_next_day/2026-04-28.json"]},
        "trade_date": "2026-04-28",
        "predict_for_trade_date": "2026-04-29",
        "predictions": [_prediction("000001.SH")],
    }

    persist_l3(l3_doc)
    l4_doc = build_l4(l3_doc)
    persist_l4(l4_doc)

    assert "data/decisions/six_index_next_day/2026-04-28.jsonl" in l3_doc["_meta"]["lineage_refs"]
    assert "data/decisions/six_index_next_day/2026-04-28.jsonl" in l4_doc["_meta"]["lineage_refs"]
    assert "data/semantic/six_index_next_day/2026-04-28.json" in l4_doc["_meta"]["lineage_refs"]


def test_predict_shanghai_no_missing_finance_reasons_when_backfilled() -> None:
    out = predict_shanghai(
        {
            "weight_sector_changes": {"bank": 0.55, "non_bank_fin": 0.45, "petro": 0.02},
            "ret10": 0.01,
            "volume_ratio_1d_5d": 1.0,
        },
        trade_date="2026-04-28",
        predict_for_trade_date="2026-04-29",
    )

    reasons = str(out.get("degraded_reason") or "")
    assert "missing_bank_sector_change" not in reasons
    assert "missing_non_bank_sector_change" not in reasons
    assert out["quality_status"] == "info"
