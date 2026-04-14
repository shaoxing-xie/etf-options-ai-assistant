"""tool_analyze_after_close_and_send_daily_report 串接入口."""

from __future__ import annotations

from unittest.mock import patch


def test_composite_calls_analyze_then_send() -> None:
    from plugins.notification import send_daily_report as m

    ac = {
        "success": True,
        "message": "ok",
        "data": {"overall_trend": "中性", "trend_strength": 0.5, "date": "2026-04-13"},
    }
    with patch("plugins.analysis.trend_analysis.tool_analyze_after_close", return_value=ac), patch.object(
        m,
        "tool_send_daily_report",
        return_value={"success": True, "message": "sent", "data": {}},
    ) as m_send:
        out = m.tool_analyze_after_close_and_send_daily_report(mode="test")
    assert out.get("success") is True
    m_send.assert_called_once()
    rd = m_send.call_args.kwargs.get("report_data") or {}
    assert rd.get("report_type") == "daily_market"
    assert rd.get("tool_analyze_after_close") is ac
    assert rd.get("analysis") == ac["data"]
