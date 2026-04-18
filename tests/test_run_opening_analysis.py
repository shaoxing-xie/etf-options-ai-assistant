"""tool_run_opening_analysis_and_send / build_opening_report_data."""

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
def patch_opening_chain() -> object:
    """Patch all plugins invoked by build_opening_report_data."""
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
    etf_rt = {"success": True, "data": [{"code": "510300", "change_percent": 0.1}]}
    tech = {"success": True, "data": {"ma": {}}}
    opening = {
        "success": True,
        "data": {
            "overall_trend": "震荡",
            "trend_strength": 0.42,
            "a50_change": None,
            "hxc_change": None,
        },
    }
    vol = {
        "success": True,
        "formatted_output": "## 📊 不应整段嵌入开盘八节",
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
    sig = {"success": True, "data": {"signals": [{"symbol": "510300", "direction": "hold"}]}}

    with patch(
        "plugins.data_collection.utils.check_trading_status.tool_check_trading_status",
        return_value=ts,
    ), patch(
        "plugins.merged.fetch_index_data.tool_fetch_index_data",
        side_effect=_mock_fetch_index_data,
    ), patch(
        "plugins.data_collection.index.fetch_global_hist_sina.tool_fetch_global_index_hist_sina",
        return_value={
            "success": True,
            "data": [
                {"date": "2026-04-09", "close": 100.0},
                {"date": "2026-04-10", "close": 101.0},
            ],
        },
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
        "plugins.merged.fetch_etf_data.tool_fetch_etf_data",
        return_value=etf_rt,
    ), patch(
        "plugins.analysis.technical_indicators.tool_calculate_technical_indicators",
        return_value=tech,
    ), patch(
        "plugins.merged.analyze_market.tool_analyze_market",
        return_value=opening,
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
    ), patch(
        "src.signal_generation.tool_generate_option_trading_signals",
        return_value=sig,
    ):
        yield


def test_build_opening_report_data_structure(patch_opening_chain: None) -> None:
    from plugins.notification.run_opening_analysis import build_opening_report_data

    rd, errs = build_opening_report_data(fetch_mode="production")
    assert rd.get("report_type") == "opening"
    assert isinstance(rd.get("analysis"), dict)
    assert rd["analysis"].get("overall_trend") == "震荡"
    assert rd.get("market_overview") and rd["market_overview"].get("indices")
    assert isinstance(rd.get("opening_market_snapshot"), dict)
    assert isinstance(rd.get("tracked_assets_snapshot"), dict)
    assert isinstance(rd.get("opening_flow_signals"), dict)
    assert isinstance(rd.get("runtime_context"), dict)
    assert isinstance(rd.get("volatility"), dict)
    assert rd.get("volatility_prediction") is None
    assert isinstance(rd.get("daily_volatility_range"), dict)
    assert not errs


def test_tool_run_opening_analysis_and_send_calls_send(patch_opening_chain: None) -> None:
    from plugins.notification.run_opening_analysis import tool_run_opening_analysis_and_send

    with patch(
        "plugins.notification.send_analysis_report.tool_send_analysis_report",
    ) as m_send:
        m_send.return_value = {"success": True, "message": "ok", "data": {}}
        out = tool_run_opening_analysis_and_send(mode="test", fetch_mode="production")
    assert out.get("success") is True
    m_send.assert_called_once()
    call_kw = m_send.call_args.kwargs
    assert call_kw.get("mode") == "test"
    rd = call_kw.get("report_data") or {}
    assert rd.get("report_type") == "opening"


def test_tool_runner_maps_composite() -> None:
    from tool_runner import TOOL_MAP

    assert "tool_run_opening_analysis_and_send" in TOOL_MAP
    spec = TOOL_MAP["tool_run_opening_analysis_and_send"]
    assert spec.module_path == "notification.run_opening_analysis"
    assert spec.function_name == "tool_run_opening_analysis_and_send"


def test_safe_step_records_error() -> None:
    from plugins.notification import run_opening_analysis as m

    errors: list = []

    def boom() -> None:
        raise RuntimeError("x")

    r = m._safe_step("boom_step", boom, errors)
    assert r is None
    assert errors == [{"step": "boom_step", "error": "x"}]
