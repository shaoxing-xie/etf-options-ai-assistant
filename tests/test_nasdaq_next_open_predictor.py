from __future__ import annotations

from unittest.mock import patch


def _build_report_data(monitor_point: str = "M7") -> dict:
    hist_events = []
    klines = []
    for i in range(1, 36):
        td = f"2026-04-{i:02d}" if i <= 30 else f"2026-05-{i-30:02d}"
        klines.append({"date": td, "open": 2.0 + i * 0.01, "close": 2.0 + i * 0.01 + (0.01 if i % 2 == 0 else -0.005)})
        if i <= 25:
            hist_events.append(
                {
                    "trade_date": td,
                    "analysis": {
                        "futures_reference": {"change_pct": 0.2 if i % 2 == 0 else 0.1},
                        "index_day_ret_pct": 0.12 if i % 2 == 0 else 0.08,
                        "range_prediction": {"core_width_pct": 2.8 if i % 3 else 3.2},
                    },
                }
            )
    return {
        "market_profile": "nasdaq_513300",
        "trade_date": "2026-05-06",
        "generated_at": "2026-05-06 14:30:00",
        "monitor_context": {"monitor_point": monitor_point},
        "analysis": {"futures_reference": {"change_pct": 0.15}, "index_day_ret_pct": 0.1, "range_prediction": {"core_width_pct": 3.1}},
        "tail_session_snapshot": {
            "latest_price": 2.55,
            "iopv_source": "realtime",
            "data_quality": "fresh",
            "valuation_blend": {"agreement_gap_pct": 1.2},
        },
        "tool_fetch_etf_historical": {"success": True, "data": {"klines": klines}},
        "_hist_events_for_test": hist_events,
    }


def test_predictor_layer2_degraded_reason_not_empty() -> None:
    from plugins.analysis.nasdaq_next_open_predictor import predict_next_open_direction

    rd = _build_report_data()
    with patch("plugins.analysis.nasdaq_next_open_predictor._load_recent_monitor_events", return_value=[]):
        out = predict_next_open_direction(rd, persist=False)
    decision = out.get("decision") if isinstance(out, dict) else {}
    sim_dbg = decision.get("similarity_debug") if isinstance(decision, dict) else {}
    assert out.get("quality_status") == "degraded"
    assert decision.get("degraded_reason")
    assert sim_dbg.get("degraded_reason_detail") == "EMPTY_MONITOR_EVENTS"


def test_predictor_m1_m6_confidence_capped_to_medium() -> None:
    from plugins.analysis.nasdaq_next_open_predictor import predict_next_open_direction

    rd = _build_report_data(monitor_point="M4")
    hist_events = rd.pop("_hist_events_for_test")
    with patch("plugins.analysis.nasdaq_next_open_predictor._load_recent_monitor_events", return_value=hist_events), patch(
        "plugins.analysis.nasdaq_next_open_predictor._fetch_tavily_event_signal",
        return_value={"success": True, "event_risk": 0.1, "note": "ok", "events": []},
    ), patch(
        "plugins.analysis.nasdaq_next_open_predictor._fetch_yf_event_signal",
        return_value={"success": True, "event_risk": 0.1, "note": "ok", "events": []},
    ):
        out = predict_next_open_direction(rd, persist=False)
    decision = out.get("decision") if isinstance(out, dict) else {}
    assert decision.get("confidence_level") in {"medium", "low"}
    assert decision.get("confidence_level") != "high"


def test_predictor_llm_called_flag_and_shift_fields() -> None:
    from plugins.analysis.nasdaq_next_open_predictor import predict_next_open_direction

    rd = _build_report_data(monitor_point="M7")
    hist_events = rd.pop("_hist_events_for_test")
    rd["analysis"]["futures_reference"]["change_pct"] = 0.0
    rd["analysis"]["index_day_ret_pct"] = 0.0
    with patch("plugins.analysis.nasdaq_next_open_predictor._load_recent_monitor_events", return_value=hist_events), patch(
        "plugins.analysis.nasdaq_next_open_predictor._fetch_tavily_event_signal",
        return_value={"success": True, "event_risk": 0.5, "note": "risk", "events": ["FOMC"]},
    ), patch(
        "plugins.analysis.nasdaq_next_open_predictor._fetch_yf_event_signal",
        return_value={"success": True, "event_risk": 0.4, "note": "risk", "events": ["MSFT"]},
    ), patch(
        "plugins.analysis.nasdaq_next_open_predictor._llm_fuse_probability",
        return_value={"success": True, "p_up_raw": 0.56, "confidence": "medium", "rationale": "test", "model_meta": {}},
    ):
        out = predict_next_open_direction(rd, persist=False)
    decision = out.get("decision") if isinstance(out, dict) else {}
    pdebug = decision.get("probability_debug") if isinstance(decision, dict) else {}
    assert pdebug.get("llm_called") is True
    assert "llm_shift" in pdebug
    assert decision.get("llm_fusion", {}).get("called") is True
