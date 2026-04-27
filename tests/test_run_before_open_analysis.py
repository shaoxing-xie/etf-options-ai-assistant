"""tool_run_before_open_analysis_and_send / build_before_open_report_data."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def _mock_fetch_index_data(**kwargs: object) -> dict:
    dt = kwargs.get("data_type")
    if dt == "global_spot":
        return {"success": True, "data": [{"code": "DJI", "name": "道指", "change_percent": 0.2}]}
    if dt == "opening":
        return {"success": True, "data": [{"code": "000300", "name": "沪深300", "change_percent": 0.1}]}
    return {"success": True, "data": [{"code": "000300", "name": "沪深300", "change_percent": 0.15}]}


@pytest.fixture
def patch_before_open_chain() -> object:
    ts = {
        "success": True,
        "data": {
            "quote_narration_rule_cn": "口径说明",
            "allows_intraday_continuous_wording": False,
        },
    }
    pn = {"success": True, "data": {"items": [{"title": "t", "url": "http://x"}]}}
    macro = {"success": True, "data": {"items": [{"name": "原油", "change_pct": 0.1}]}}
    od = {
        "success": True,
        "data": {
            "a50_digest": "a50 sum",
            "hxc_digest": "hxc sum",
            "evidence_urls": [],
        },
    }
    ann = {"success": True, "data": {"items": []}}
    sector = {"success": True, "sectors": [{"name": "半导体", "score": 50.0}]}
    kl = {"success": True, "data": {"support": 4000.0, "resistance": 4100.0}}
    before_open = {
        "success": True,
        "data": {
            "overall_trend": "偏多",
            "trend_strength": 0.55,
            "a50_change": None,
            "hxc_change": None,
        },
    }
    vol = {
        "success": True,
        "formatted_output": "## 波动摘要",
        "data": {
            "success": True,
            "type": "etf",
            "current_price": 4.6,
            "upper": 4.7,
            "lower": 4.5,
            "range_pct": 1.5,
            "confidence": 0.6,
        },
    }
    intr = {"success": True, "data": {"upper": 4.7, "lower": 4.5, "confidence": 0.6}}
    dvol = {"success": True, "data": {"upper": 4.8, "lower": 4.4, "range_pct": 2.1}}
    prev = {"success": True, "data": {"review": None}}

    with patch(
        "plugins.data_collection.utils.check_trading_status.tool_check_trading_status",
        return_value=ts,
    ), patch(
        "plugins.merged.fetch_index_data.tool_fetch_index_data",
        side_effect=_mock_fetch_index_data,
    ), patch(
        "plugins.data_collection.morning_brief_fetchers.tool_fetch_policy_news",
        return_value=pn,
    ), patch(
        "plugins.data_collection.morning_brief_fetchers.tool_fetch_macro_commodities",
        return_value=macro,
    ), patch(
        "plugins.data_collection.morning_brief_fetchers.tool_fetch_overnight_futures_digest",
        return_value=od,
    ), patch(
        "plugins.data_collection.morning_brief_fetchers.tool_fetch_announcement_digest",
        return_value=ann,
    ), patch(
        "plugins.data_collection.limit_up.sector_heat.tool_sector_heat_score",
        return_value=sector,
    ), patch(
        "plugins.analysis.key_levels.tool_compute_index_key_levels",
        return_value=kl,
    ), patch(
        "plugins.analysis.trend_analysis.tool_analyze_before_open",
        return_value=before_open,
    ), patch(
        "plugins.merged.volatility.tool_volatility",
        return_value=vol,
    ), patch(
        "plugins.analysis.intraday_range.tool_predict_intraday_range",
        return_value=intr,
    ), patch(
        "plugins.analysis.daily_volatility_range.tool_predict_daily_volatility_range",
        return_value=dvol,
    ), patch(
        "plugins.analysis.accuracy_tracker.tool_get_yesterday_prediction_review",
        return_value=prev,
    ):
        yield


def test_build_before_open_report_data_structure(patch_before_open_chain: None) -> None:
    from plugins.notification.run_before_open_analysis import build_before_open_report_data

    rd, errs = build_before_open_report_data(fetch_mode="production")
    assert rd.get("report_type") == "before_open"
    assert isinstance(rd.get("generated_at"), str) and rd["generated_at"]
    assert isinstance(rd.get("analysis"), dict)
    assert rd["analysis"].get("overall_trend") == "偏多"
    assert rd.get("market_overview") and rd["market_overview"].get("indices")
    assert isinstance(rd.get("volatility"), dict)
    assert isinstance(rd.get("daily_volatility_range"), dict)
    assert not errs


def test_tool_run_before_open_analysis_and_send_calls_send(patch_before_open_chain: None) -> None:
    from plugins.notification.run_before_open_analysis import tool_run_before_open_analysis_and_send

    with patch(
        "plugins.notification.send_analysis_report.tool_send_analysis_report",
    ) as m_send:
        m_send.return_value = {"success": True, "message": "ok", "data": {}}
        out = tool_run_before_open_analysis_and_send(mode="test", fetch_mode="production")
    assert out.get("success") is True
    m_send.assert_called_once()
    call_kw = m_send.call_args.kwargs
    assert call_kw.get("mode") == "test"
    rd = call_kw.get("report_data") or {}
    assert rd.get("report_type") == "before_open"


def test_tool_runner_maps_before_open_composite() -> None:
    from tool_runner import TOOL_MAP

    assert "tool_run_before_open_analysis_and_send" in TOOL_MAP
    spec = TOOL_MAP["tool_run_before_open_analysis_and_send"]
    assert spec.module_path == "notification.run_before_open_analysis"
    assert spec.function_name == "tool_run_before_open_analysis_and_send"


def test_build_before_open_marks_analysis_health_degraded_when_analysis_missing(
    patch_before_open_chain: None,
) -> None:
    from plugins.notification.run_before_open_analysis import build_before_open_report_data

    with patch(
        "plugins.analysis.trend_analysis.tool_analyze_before_open",
        return_value={"success": False, "message": "analysis unavailable", "data": None},
    ):
        rd, _errs = build_before_open_report_data(fetch_mode="production")

    ah = rd.get("analysis_health")
    assert isinstance(ah, dict)
    assert ah.get("status") == "degraded"
    assert "analysis_tool_failed" in str(ah.get("reason") or "")
