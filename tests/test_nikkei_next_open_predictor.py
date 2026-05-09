from __future__ import annotations

from unittest.mock import patch


def _base_report_data(monitor_point: str = "M6") -> dict:
    return {
        "trade_date": "2026-04-29",
        "monitor_context": {"monitor_point": monitor_point},
        "analysis": {
            "index_day_ret_pct": -0.8,
            "rsi14": 55.0,
            "futures_reference": {"change_pct": 1.0},
            "deviation_proxy": {"deviation_pct": 0.2},
        },
        "analysis_premium": {"quality_status": "ok"},
        "next_open_nikkei_samples": 30,
    }


def test_layer1_calibration_for_plus_one_percent() -> None:
    from plugins.analysis.nikkei_next_open_predictor import predict_next_open_direction

    rd = _base_report_data()
    with patch(
        "plugins.analysis.nikkei_next_open_predictor.calculate_event_gate",
        return_value={"event_risk": 0.1, "event_triggers": [], "impact_templates": [], "event_note": "ok", "source_status": "ok"},
    ):
        out = predict_next_open_direction(rd)
    c0 = out["decision"]["components"][0]
    score = float(c0["score"])
    assert 0.55 <= score <= 0.65


def test_confidence_medium_on_normal_day_with_m6_cap() -> None:
    from plugins.analysis.nikkei_next_open_predictor import predict_next_open_direction

    rd = _base_report_data(monitor_point="M6")
    with patch(
        "plugins.analysis.nikkei_next_open_predictor.calculate_event_gate",
        return_value={"event_risk": 0.1, "event_triggers": [], "impact_templates": [], "event_note": "ok", "source_status": "ok"},
    ):
        out = predict_next_open_direction(rd)
    assert out["decision"]["confidence_level"] == "medium"
    assert out["decision"].get("confidence_reason")


def test_discount_converging_raises_p_up_vs_neutral() -> None:
    from plugins.analysis.nikkei_next_open_predictor import predict_next_open_direction

    gate = {"event_risk": 0.08, "event_triggers": [], "impact_templates": [], "event_note": "ok", "source_status": "ok"}
    rd_neutral = _base_report_data()
    rd_neutral["analysis"]["deviation_proxy"] = {"deviation_pct": 0.1, "deviation_trend": "sideways"}
    rd_neutral["analysis_premium"] = {"quality_status": "ok", "premium_rate_pct": -0.5}
    with patch("plugins.analysis.nikkei_next_open_predictor.calculate_event_gate", return_value=gate):
        out_n = predict_next_open_direction(rd_neutral)
    rd_disc = _base_report_data()
    rd_disc["analysis"]["deviation_proxy"] = {"deviation_pct": -5.5, "deviation_trend": "converging"}
    rd_disc["analysis_premium"] = {"quality_status": "ok", "premium_rate_pct": -4.2}
    with patch("plugins.analysis.nikkei_next_open_predictor.calculate_event_gate", return_value=gate):
        out_d = predict_next_open_direction(rd_disc)
    assert float(out_d["decision"]["p_up"]) > float(out_n["decision"]["p_up"])


def test_event_gate_integration_exposes_triggers() -> None:
    from plugins.analysis.nikkei_next_open_predictor import predict_next_open_direction

    rd = _base_report_data(monitor_point="M1")
    with patch(
        "plugins.analysis.nikkei_next_open_predictor.calculate_event_gate",
        return_value={
            "event_risk": 0.55,
            "event_triggers": ["FOMC", "美国CPI"],
            "impact_templates": [{"event": "FOMC", "impact_note": "隔夜美盘情绪→日经期货→次日开盘"}],
            "event_note": "ok",
            "source_status": "ok",
        },
    ):
        out = predict_next_open_direction(rd)
    event_gate = out["decision"].get("event_gate") or {}
    assert event_gate.get("event_risk", 0) > 0
    assert "FOMC" in (event_gate.get("event_triggers") or [])
