from __future__ import annotations

from unittest.mock import patch


def test_event_gate_with_boj_and_fomc_events() -> None:
    from plugins.analysis.nikkei_event_gate import calculate_event_gate

    with patch(
        "plugins.analysis.nikkei_event_gate._fetch_tavily_events",
        return_value={"success": True, "note": "ok", "events": ["BOJ会议", "FOMC"]},
    ), patch(
        "plugins.analysis.nikkei_event_gate._fetch_event_sentinel_events",
        return_value={"success": True, "note": "ok", "events": []},
    ):
        out = calculate_event_gate("2026-04-29")
    assert out["event_risk"] >= 0.3
    assert "BOJ会议" in out["event_triggers"]
    impacts = out.get("impact_templates") if isinstance(out.get("impact_templates"), list) else []
    assert impacts and impacts[0].get("impact_note")


def test_event_gate_degraded_fallback_not_blocking() -> None:
    from plugins.analysis.nikkei_event_gate import calculate_event_gate

    with patch(
        "plugins.analysis.nikkei_event_gate._fetch_tavily_events",
        return_value={"success": False, "note": "timeout", "events": []},
    ), patch(
        "plugins.analysis.nikkei_event_gate._fetch_event_sentinel_events",
        return_value={"success": False, "note": "timeout", "events": []},
    ):
        out = calculate_event_gate("2026-04-30")
    assert out["source_status"] == "degraded"
    assert isinstance(out.get("event_triggers"), list)
