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
    with patch("plugins.analysis.trend_analysis.tool_analyze_after_close", return_value=ac), patch(
        "plugins.notification.daily_report_normalization._maybe_autofill_cron_daily_market_p0",
        return_value=None,
    ), patch(
        "plugins.data_collection.limit_up.sector_heat.tool_sector_heat_score",
        return_value={"success": True, "data": {}},
    ), patch(
        "plugins.data_collection.a_share_fund_flow.tool_fetch_a_share_fund_flow",
        return_value={"success": True, "data": {}},
    ), patch(
        "plugins.data_access.policy_news.tool_fetch_policy_news",
        return_value={"success": True, "data": []},
    ), patch(
        "plugins.data_collection.morning_brief_fetchers.tool_fetch_industry_news_brief",
        return_value={"success": True, "data": []},
    ), patch(
        "plugins.data_collection.morning_brief_fetchers.tool_fetch_announcement_digest",
        return_value={"success": True, "data": []},
    ), patch(
        "plugins.merged.fetch_etf_data.tool_fetch_etf_data",
        return_value={"success": True, "data": {}},
    ), patch(
        "plugins.merged.fetch_index_data.tool_fetch_index_data",
        return_value={"success": True, "data": []},
    ), patch(
        "plugins.analysis.daily_volatility_range.tool_predict_daily_volatility_range",
        return_value={"success": True, "data": {}},
    ), patch(
        "src.signal_generation.tool_generate_option_trading_signals",
        return_value={"success": True, "data": {}},
    ), patch.object(
        m,
        "tool_send_daily_report",
        return_value={"success": True, "message": "sent", "data": {}},
    ) as m_send:
        out = m.tool_analyze_after_close_and_send_daily_report(mode="test")
    assert out.get("success") is True
    m_send.assert_called_once()
    rd = m_send.call_args.kwargs.get("report_data") or {}
    assert rd.get("report_type") == "daily_market"
    assert rd.get("tool_analyze_after_close") == ac
    assert rd.get("analysis") == ac["data"]
