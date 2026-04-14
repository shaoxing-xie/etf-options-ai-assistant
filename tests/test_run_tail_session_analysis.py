from __future__ import annotations

from unittest.mock import patch


def _mock_fetch_index_data(**kwargs: object) -> dict:
    dt = kwargs.get("data_type")
    if dt == "global_spot":
        return {
            "success": True,
            "data": [
                {"code": "^IXIC", "name": "纳指", "change_pct": 0.5},
                {"code": "^N225", "name": "日经225", "change_pct": 0.2},
            ],
        }
    return {"success": True, "data": []}


def test_build_tail_session_report_data_structure() -> None:
    from plugins.notification.run_tail_session_analysis import build_tail_session_report_data

    with patch(
        "plugins.data_collection.utils.check_trading_status.tool_check_trading_status",
        return_value={"success": True, "data": {"market_status": "open"}},
    ), patch(
        "plugins.data_collection.etf.fetch_realtime.tool_fetch_etf_iopv_snapshot",
        return_value={
            "success": True,
            "data": {"code": "513880", "latest_price": 1.23, "iopv": 1.20, "discount_pct": -2.5},
        },
    ), patch(
        "plugins.merged.fetch_etf_data.tool_fetch_etf_data",
        return_value={"success": True, "data": {"code": "513880", "current_price": 1.23, "amount": 50000000}},
    ), patch(
        "plugins.data_collection.index.fetch_global_hist_sina.tool_fetch_global_index_hist_sina",
        return_value={
            "success": True,
            "data": [{"close": 100 + i} for i in range(40)],
        },
    ), patch(
        "plugins.merged.fetch_index_data.tool_fetch_index_data",
        side_effect=_mock_fetch_index_data,
    ):
        rd, errs = build_tail_session_report_data(fetch_mode="test")

    assert rd.get("report_type") == "tail_session"
    assert isinstance(rd.get("analysis"), dict)
    assert isinstance(rd["analysis"].get("layer_outputs"), list)
    assert isinstance(rd["analysis"].get("decision_options"), dict)
    assert isinstance(rd["analysis"].get("risk_notices"), list)
    assert isinstance(rd.get("tail_session_snapshot"), dict)
    assert rd["tail_session_snapshot"].get("iopv_source") == "realtime"
    assert errs == []


def test_tool_run_tail_session_analysis_and_send_calls_sender() -> None:
    from plugins.notification.run_tail_session_analysis import tool_run_tail_session_analysis_and_send

    with patch(
        "plugins.notification.run_tail_session_analysis.build_tail_session_report_data",
        return_value=(
            {"report_type": "tail_session", "analysis": {"layer_outputs": []}},
            [],
        ),
    ), patch(
        "plugins.notification.send_analysis_report.tool_send_analysis_report",
        return_value={"success": True, "data": {}},
    ) as m_send:
        out = tool_run_tail_session_analysis_and_send(mode="test")

    assert out.get("success") is True
    m_send.assert_called_once()
    assert m_send.call_args.kwargs.get("mode") == "test"


def test_build_tail_session_manual_iopv_override() -> None:
    from plugins.notification.run_tail_session_analysis import build_tail_session_report_data

    with patch(
        "plugins.notification.run_tail_session_analysis._load_market_data_cfg",
        return_value={
            "iopv_fallback": {
                "manual_iopv_overrides": {
                        "513880": {"updated_date": "2026-04-14", "iopv": 1.21, "source": "manual_after_14_00"}
                },
                "estimation": {"enabled": False},
            }
        },
    ), patch(
        "plugins.notification.run_tail_session_analysis._now_sh",
        return_value=__import__("datetime").datetime(2026, 4, 14, 14, 50, 0),
    ), patch(
        "plugins.data_collection.utils.check_trading_status.tool_check_trading_status",
        return_value={"success": True, "data": {"market_status": "open"}},
    ), patch(
        "plugins.data_collection.etf.fetch_realtime.tool_fetch_etf_iopv_snapshot",
        return_value={"success": True, "data": {"code": "513880", "latest_price": 1.23, "iopv": None, "discount_pct": None}},
    ), patch(
        "plugins.merged.fetch_etf_data.tool_fetch_etf_data",
        return_value={"success": True, "data": {"code": "513880", "current_price": 1.23, "amount": 50000000}},
    ), patch(
        "plugins.data_collection.index.fetch_global_hist_sina.tool_fetch_global_index_hist_sina",
        return_value={"success": True, "data": [{"close": 100 + i} for i in range(40)]},
    ), patch(
        "plugins.merged.fetch_index_data.tool_fetch_index_data",
        side_effect=_mock_fetch_index_data,
    ):
        rd, errs = build_tail_session_report_data(fetch_mode="test")

    snap = rd["tail_session_snapshot"]
    assert snap.get("iopv_source") == "manual"
    assert snap.get("iopv") == 1.21
    assert errs == []


def test_tool_runner_maps_tail_composite() -> None:
    from tool_runner import TOOL_MAP

    assert "tool_run_tail_session_analysis_and_send" in TOOL_MAP
    spec = TOOL_MAP["tool_run_tail_session_analysis_and_send"]
    assert spec.module_path == "notification.run_tail_session_analysis"
    assert spec.function_name == "tool_run_tail_session_analysis_and_send"
