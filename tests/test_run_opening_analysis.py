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
    etf_rt = {
        "success": True,
        "data": [
            {"code": "510300", "name": "沪深300ETF", "change_percent": 0.1, "volume_ratio": 1.1},
            {"code": "159997", "name": "电子ETF", "change_percent": 0.9, "volume_ratio": 1.4},
            {"code": "515880", "name": "通信ETF", "change_percent": 0.3, "volume_ratio": 1.05},
            {"code": "512200", "name": "地产ETF", "change_percent": -0.6, "volume_ratio": 0.8},
        ],
    }
    rotation_loaded = {
        "quality_status": "ok",
        "degraded_reason": "",
        "rotation_trade_date": "2026-04-30",
        "path": "data/semantic/rotation_latest/2026-04-30.json",
        "data": {
            "unified_next_day": [
                {"rank": 1, "etf_code": "159997", "etf_name": "电子ETF", "unified_score": 0.86},
                {"rank": 2, "etf_code": "515880", "etf_name": "通信ETF", "unified_score": 0.74},
            ],
            "legacy_views": {
                "rps_recommendations": [
                    {"rank": 1, "etf_code": "159997", "etf_name": "电子ETF", "composite_score": 0.86},
                    {"rank": 2, "etf_code": "512200", "etf_name": "地产ETF", "composite_score": 0.68},
                ],
                "three_factor_top5": [
                    {"rank": 1, "symbol": "515880", "name": "通信ETF", "score": 0.74},
                    {"rank": 2, "symbol": "512200", "name": "地产ETF", "score": 0.67},
                ],
            },
            "sector_environment_effective": {"effective_gate": "GO"},
        },
    }
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
        "plugins.notification.run_opening_analysis._load_rotation_latest_for_opening",
        return_value=rotation_loaded,
    ), patch(
        "plugins.notification.run_opening_analysis._previous_trading_day_ymd",
        return_value="2026-04-30",
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
    assert isinstance(rd.get("rotation_opening_candidates"), list)
    assert isinstance(rd.get("rotation_opening_validation"), list)
    assert isinstance(rd.get("rotation_trading_suggestions"), dict)
    assert isinstance(rd.get("rotation_validation_quality"), dict)
    assert isinstance(rd.get("rotation_data_freshness"), dict)
    assert rd["rotation_validation_quality"].get("quality_status") == "ok"
    assert rd["rotation_data_freshness"].get("rotation_trade_date") == "2026-04-30"
    assert rd["rotation_data_freshness"].get("is_prev_trading_day") is True
    assert isinstance(rd.get("overnight_bias_vote"), list)
    assert rd.get("overnight_bias_label") in ("偏强", "分化", "谨慎偏弱")
    assert isinstance(rd.get("trend_resolution"), dict)
    assert isinstance(rd.get("holiday_position_hint"), dict)
    assert isinstance(rd.get("policy_event_quality"), dict)
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


def test_tool_run_opening_analysis_stop_gate_only_observe() -> None:
    from plugins.notification.run_opening_analysis import tool_run_opening_analysis_and_send

    mocked_report_data = {
        "report_type": "opening",
        "rotation_trading_suggestions": {
            "market_gate": "STOP",
            "main_actions": [],
            "observe_list": [{"etf_code": "159997"}],
            "risk_controls": ["环境门闸为 STOP，本栏目仅保留观察，不输出主建议。"],
        },
        "rotation_validation_quality": {"quality_status": "ok"},
    }

    with patch(
        "plugins.notification.run_opening_analysis.build_opening_report_data",
        return_value=(mocked_report_data, []),
    ), patch(
        "plugins.notification.send_analysis_report.tool_send_analysis_report",
    ) as m_send:
        m_send.return_value = {"success": True, "message": "ok", "data": {}}
        out = tool_run_opening_analysis_and_send(
            mode="test",
            fetch_mode="test",
            report_variant="realtime",
            workflow_profile="legacy",
        )

    assert out.get("success") is True
    m_send.assert_called_once()
    rd = m_send.call_args.kwargs.get("report_data") or {}
    sugg = rd.get("rotation_trading_suggestions") if isinstance(rd.get("rotation_trading_suggestions"), dict) else {}
    assert str(sugg.get("market_gate") or "").upper() == "STOP"
    assert sugg.get("main_actions") == []
    obs = sugg.get("observe_list") if isinstance(sugg.get("observe_list"), list) else []
    assert isinstance(obs, list)


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


def test_build_opening_marks_analysis_health_degraded_when_analysis_missing(
    patch_opening_chain: None,
) -> None:
    from plugins.notification.run_opening_analysis import build_opening_report_data

    with patch(
        "plugins.merged.analyze_market.tool_analyze_market",
        return_value={"success": False, "message": "analysis unavailable", "data": None},
    ):
        rd, _errs = build_opening_report_data(fetch_mode="production")

    ah = rd.get("analysis_health")
    assert isinstance(ah, dict)
    assert ah.get("status") == "degraded"
    assert "analysis_tool_failed" in str(ah.get("reason") or "")


def test_overnight_bias_replay_20260429_score_is_negative() -> None:
    from plugins.notification import run_opening_analysis as m

    rd = {
        "market_overview": {
            "indices": [
                {"code": "A50", "change_pct": -0.51},
                {"code": "^N225", "change_pct": -1.02},
                {"code": "^DJI", "change_pct": -0.57},
                {"code": "^GSPC", "change_pct": -0.04},
                {"code": "^IXIC", "change_pct": 0.04},
            ]
        }
    }
    out = m._build_overnight_bias(rd)
    assert float(out.get("score") or 0.0) < -0.2
    assert out.get("label") == "谨慎偏弱"
    assert int(out.get("matched_count") or 0) == 5


def test_conflict_resolution_downgrades_strong_local_bias() -> None:
    from plugins.notification import run_opening_analysis as m

    rd = {
        "analysis": {"overall_trend": "偏强", "trend_strength": 0.8},
        "market_overview": {
            "indices": [
                {"code": "A50", "change_pct": -0.51},
                {"code": "^N225", "change_pct": -1.02},
                {"code": "^DJI", "change_pct": -0.57},
                {"code": "^GSPC", "change_pct": -0.04},
                {"code": "^IXIC", "change_pct": 0.04},
            ]
        },
    }
    m._apply_opening_trend_resolution(rd)
    tr = rd.get("trend_resolution") or {}
    assert tr.get("conflict") is True
    assert "分化" in str(rd.get("overall_trend") or "")


def test_trend_fields_present_when_no_conflict() -> None:
    """
    回归保护：同向场景（conflict=False）也必须写入 overall_trend / trend_strength，
    否则报告会渲染为 N/A。
    """
    from plugins.notification import run_opening_analysis as m

    rd = {
        # 本地信号与外盘同向（都偏弱），不应触发 conflict
        "analysis": {"overall_trend": "偏弱", "trend_strength": -0.1},
        "market_overview": {
            "indices": [
                {"code": "A50", "change_pct": -0.51},
                {"code": "^N225", "change_pct": -1.02},
                {"code": "^DJI", "change_pct": -0.57},
                {"code": "^GSPC", "change_pct": -0.04},
                {"code": "^IXIC", "change_pct": 0.04},
            ]
        },
    }
    m._apply_opening_trend_resolution(rd)
    tr = rd.get("trend_resolution") or {}
    assert tr.get("conflict") is False
    assert rd.get("overall_trend") is not None
    assert isinstance(rd.get("trend_strength"), (int, float))


def test_policy_event_quality_error_when_fed_vote_missing() -> None:
    from plugins.notification import run_opening_analysis as m

    rd = {
        "tool_fetch_policy_news": {
            "success": True,
            "data": {
                "brief_answer": "美联储维持利率不变，市场关注未来路径。",
                "items": [{"title": "FOMC meeting concludes", "summary": "rate unchanged"}],
            },
        }
    }
    m._build_policy_event_signals(rd)
    pq = rd.get("policy_event_quality") or {}
    assert pq.get("quality_status") == "error"
    assert "vote_split" in str(pq.get("degraded_reason") or "")
    assert "reason_codes" in pq
    assert "required_fields" in pq


def test_overnight_bias_alias_supports_chinese_index_names() -> None:
    from plugins.notification import run_opening_analysis as m

    rd = {
        "market_overview": {
            "indices": [
                {"name": "道琼斯", "change_pct": -0.57},
                {"name": "标普500", "change_pct": -0.04},
                {"name": "纳斯达克", "change_pct": 0.04},
                {"name": "日经225", "change_pct": -1.02},
                {"name": "A50期指", "change_pct": -0.51},
            ]
        }
    }
    out = m._build_overnight_bias(rd)
    assert int(out.get("matched_count") or 0) == 5


def test_policy_event_quality_ok_with_strong_fomc_fields() -> None:
    from plugins.notification import run_opening_analysis as m

    rd = {
        "tool_fetch_policy_news": {
            "success": True,
            "data": {
                "brief_answer": "FOMC维持利率不变，投票8比4，声明偏鹰，市场下调年内降息预期。",
                "items": [{"title": "FOMC vote 8-4 hold rates", "summary": "higher for longer"}],
            },
        }
    }
    m._build_policy_event_signals(rd)
    pq = rd.get("policy_event_quality") or {}
    events = rd.get("policy_event_signals") or []
    assert pq.get("quality_status") == "ok"
    assert isinstance(events, list) and events
    fomc = next((e for e in events if e.get("event_type") == "FOMC"), {})
    assert fomc.get("vote_split") == "8-4"
    assert fomc.get("rate_decision") == "hold"


def test_cross_check_index_etf_consistency_flags_direction_and_gap() -> None:
    from plugins.notification import run_opening_analysis as m

    idx_rows = [{"code": "000300", "change_pct": -0.09, "timestamp": "2026-04-30 10:37:03"}]
    etf_rows = [{"code": "510300", "change_pct": 1.11, "timestamp": "2026-04-30 10:37:03"}]
    flags = m._cross_check_index_etf_consistency(
        idx_rows=idx_rows,
        etf_rows=etf_rows,
        snapshot_time="2026-04-30 10:37:03",
    )
    codes = {str(x.get("code")) for x in flags if isinstance(x, dict)}
    assert "direction_conflict" in codes
    assert "large_basis_gap" in codes


def test_cross_check_index_etf_consistency_flags_stale_data() -> None:
    from plugins.notification import run_opening_analysis as m

    idx_rows = [{"code": "000300", "change_pct": 0.09, "timestamp": "2026-04-30 10:20:00"}]
    etf_rows = [{"code": "510300", "change_pct": 0.11, "timestamp": "2026-04-30 10:20:10"}]
    flags = m._cross_check_index_etf_consistency(
        idx_rows=idx_rows,
        etf_rows=etf_rows,
        snapshot_time="2026-04-30 10:37:03",
    )
    codes = {str(x.get("code")) for x in flags if isinstance(x, dict)}
    assert "stale_data" in codes
