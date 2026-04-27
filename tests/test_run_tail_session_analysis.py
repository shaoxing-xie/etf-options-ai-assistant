from __future__ import annotations

from io import BytesIO
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
        rd, errs = build_tail_session_report_data(fetch_mode="test", market_profile="nasdaq_513300")

    assert rd.get("report_type") == "tail_session"
    assert isinstance(rd.get("analysis"), dict)
    assert isinstance(rd["analysis"].get("layer_outputs"), list)
    assert isinstance(rd["analysis"].get("decision_options"), dict)
    assert isinstance(rd["analysis"].get("risk_notices"), list)
    assert isinstance(rd.get("tail_session_snapshot"), dict)
    assert rd["tail_session_snapshot"].get("iopv_source") in {"realtime", "manual", "estimated", "proxy_deviation"}
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
        return_value={
            "success": True,
            "delivery": {"ok": True, "status": "ok", "errcode": 0, "errmsg": "ok"},
            "response": {"errcode": 0, "errmsg": "ok", "http_status": 200},
            "data": {},
        },
    ) as m_send:
        out = tool_run_tail_session_analysis_and_send(mode="test")

    assert out.get("success") is True
    m_send.assert_called_once()
    assert m_send.call_args.kwargs.get("mode") == "test"
    assert out.get("delivered") is True
    assert out.get("deliveryStatus") == "ok"
    out_data = out.get("data") if isinstance(out.get("data"), dict) else {}
    delivery = out_data.get("delivery") if isinstance(out_data.get("delivery"), dict) else {}
    assert delivery.get("attempted") is True
    assert delivery.get("success") is True
    assert delivery.get("channel_code") == 0


def test_build_tail_session_manual_iopv_override() -> None:
    from plugins.notification.run_tail_session_analysis import build_tail_session_report_data

    with patch(
        "plugins.notification.run_tail_session_analysis._load_market_data_cfg",
        return_value={
            "iopv_fallback": {
                "manual_iopv_overrides": {
                        "513300": {"updated_date": "2026-04-14", "iopv": 1.21, "source": "manual_after_14_00"}
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
        rd, errs = build_tail_session_report_data(fetch_mode="test", market_profile="nasdaq_513300")

    snap = rd["tail_session_snapshot"]
    assert snap.get("iopv_source") in {"manual", "proxy_deviation"}
    assert snap.get("iopv") == 1.21
    assert errs == []


def test_tool_runner_maps_tail_composite() -> None:
    from tool_runner import TOOL_MAP

    assert "tool_run_tail_session_analysis_and_send" in TOOL_MAP
    spec = TOOL_MAP["tool_run_tail_session_analysis_and_send"]
    assert spec.module_path == "notification.run_tail_session_analysis"
    assert spec.function_name == "tool_run_tail_session_analysis_and_send"


def test_build_tail_session_nasdaq_valuation_blend_and_temperature() -> None:
    from plugins.notification.run_tail_session_analysis import build_tail_session_report_data

    class _Resp:
        def __init__(self, text: str) -> None:
            self._buf = BytesIO(text.encode("utf-8"))

        def read(self) -> bytes:
            return self._buf.read()

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(url: str, timeout: float = 5.0) -> _Resp:
        _ = (url, timeout)
        return _Resp(
            'jsonpgz({"fundcode":"513300","name":"纳斯达克ETF华夏","jzrq":"2026-04-23","dwjz":"2.2900","gsz":"2.2600","gszzl":"-0.55","gztime":"2026-04-24 14:29:00"});'
        )

    with patch(
        "plugins.notification.run_tail_session_analysis.urlopen",
        side_effect=_fake_urlopen,
    ), patch(
        "plugins.notification.run_tail_session_analysis._now_sh",
        return_value=__import__("datetime").datetime(2026, 4, 24, 14, 30, 0),
    ), patch(
        "plugins.data_collection.utils.check_trading_status.tool_check_trading_status",
        return_value={"success": True, "data": {"market_status": "open"}},
    ), patch(
        "plugins.data_collection.etf.fetch_realtime.tool_fetch_etf_iopv_snapshot",
        return_value={"success": True, "data": {"code": "513300", "latest_price": 2.33, "iopv": None, "discount_pct": None}},
    ), patch(
        "plugins.merged.fetch_etf_data.tool_fetch_etf_data",
        return_value={"success": True, "data": {"code": "513300", "current_price": 2.33, "amount": 80000000, "change_pct": 1.2}},
    ), patch(
        "plugins.data_collection.index.fetch_global_hist_sina.tool_fetch_global_index_hist_sina",
        return_value={"success": True, "data": [{"close": 100 + i} for i in range(40)]},
    ), patch(
        "plugins.merged.fetch_index_data.tool_fetch_index_data",
        side_effect=_mock_fetch_index_data,
    ), patch(
        "plugins.notification.run_tail_session_analysis._fetch_nq_futures_snapshot",
        return_value={"status": "ok", "symbol": "NQ=F", "change_pct": 0.5},
    ):
        rd, errs = build_tail_session_report_data(
            fetch_mode="test",
            market_profile="nasdaq_513300",
            monitor_point="M4",
        )

    snap = rd.get("tail_session_snapshot") or {}
    blend = snap.get("valuation_blend") if isinstance(snap, dict) else {}
    analysis = rd.get("analysis") if isinstance(rd.get("analysis"), dict) else {}
    assert isinstance(blend, dict)
    assert blend.get("confidence") in {"high", "medium", "low"}
    assert analysis.get("temperature_band") in {"cold", "normal", "warm", "hot", "unknown"}
    assert "premium_percentile_20d" in analysis
    assert errs == [] or isinstance(errs, list)


def test_build_tail_session_nikkei_theoretical_nav_as_iopv() -> None:
    from plugins.notification.run_tail_session_analysis import build_tail_session_report_data

    with patch(
        "plugins.notification.run_tail_session_analysis._now_sh",
        return_value=__import__("datetime").datetime(2026, 4, 24, 14, 33, 59),
    ), patch(
        "plugins.data_collection.utils.check_trading_status.tool_check_trading_status",
        return_value={"success": True, "data": {"market_status": "open"}},
    ), patch(
        "plugins.data_collection.etf.fetch_realtime.tool_fetch_etf_iopv_snapshot",
        return_value={"success": True, "data": {"code": "513880", "latest_price": 1.872, "iopv": None, "discount_pct": None}},
    ), patch(
        "plugins.merged.fetch_etf_data.tool_fetch_etf_data",
        return_value={"success": True, "data": {"code": "513880", "current_price": 1.872, "amount": 98000000, "change_pct": 0.9}},
    ), patch(
        "plugins.data_collection.index.fetch_global_hist_sina.tool_fetch_global_index_hist_sina",
        return_value={"success": True, "data": [{"close": 100 + i} for i in range(40)]},
    ), patch(
        "plugins.merged.fetch_index_data.tool_fetch_index_data",
        side_effect=_mock_fetch_index_data,
    ), patch(
        "plugins.notification.run_tail_session_analysis._fetch_fundgz_snapshot",
        return_value={"status": "ok", "official_nav": 1.85, "nav_date": "2026-04-23"},
    ), patch(
        "plugins.notification.run_tail_session_analysis._fetch_nikkei_futures_snapshot",
        return_value={"status": "unavailable"},
    ):
        rd, errs = build_tail_session_report_data(fetch_mode="test", market_profile="nikkei_513880", monitor_point="M7")

    snap = rd.get("tail_session_snapshot") or {}
    assert snap.get("iopv_source") == "theoretical_nav"
    assert snap.get("iopv") is not None
    assert errs == []


def test_build_tail_session_nikkei_m6_next_open_direction_with_degrade() -> None:
    from plugins.notification.run_tail_session_analysis import build_tail_session_report_data

    with patch(
        "plugins.notification.run_tail_session_analysis._now_sh",
        return_value=__import__("datetime").datetime(2026, 4, 24, 13, 45, 0),
    ), patch(
        "plugins.data_collection.utils.check_trading_status.tool_check_trading_status",
        return_value={"success": True, "data": {"market_status": "open"}},
    ), patch(
        "plugins.data_collection.etf.fetch_realtime.tool_fetch_etf_iopv_snapshot",
        return_value={"success": True, "data": {"code": "513880", "latest_price": 1.872, "iopv": None, "discount_pct": None}},
    ), patch(
        "plugins.merged.fetch_etf_data.tool_fetch_etf_data",
        return_value={"success": True, "data": {"code": "513880", "current_price": 1.872, "amount": 98000000, "change_pct": 0.9}},
    ), patch(
        "plugins.data_collection.index.fetch_global_hist_sina.tool_fetch_global_index_hist_sina",
        return_value={"success": True, "data": [{"close": 100 + i} for i in range(40)]},
    ), patch(
        "plugins.merged.fetch_index_data.tool_fetch_index_data",
        side_effect=_mock_fetch_index_data,
    ), patch(
        "plugins.notification.run_tail_session_analysis._fetch_fundgz_snapshot",
        return_value={"status": "ok", "official_nav": 1.85, "nav_date": "2026-04-23"},
    ), patch(
        "plugins.notification.run_tail_session_analysis._fetch_nikkei_futures_snapshot",
        return_value={"status": "unavailable"},
    ):
        rd, errs = build_tail_session_report_data(fetch_mode="test", market_profile="nikkei_513880", monitor_point="M6")

    pred = rd.get("next_open_direction") if isinstance(rd.get("next_open_direction"), dict) else {}
    assert pred.get("direction") in {"up", "down"}
    assert isinstance(pred.get("p_up"), float)
    assert pred.get("confidence_level") == "low"
    assert "PREDICTOR_NO_FUTURES_DATA" in str(pred.get("degraded_reason") or "")
    backtest_stats = pred.get("backtest_stats") if isinstance(pred.get("backtest_stats"), dict) else {}
    assert backtest_stats.get("required_samples") == 20
    assert "current_samples" in backtest_stats
    assert errs == []


def test_build_tail_session_required_minimum_fields_present() -> None:
    from plugins.notification.run_tail_session_analysis import build_tail_session_report_data

    with patch(
        "plugins.data_collection.utils.check_trading_status.tool_check_trading_status",
        return_value={"success": True, "data": {"market_status": "open"}},
    ), patch(
        "plugins.data_collection.etf.fetch_realtime.tool_fetch_etf_iopv_snapshot",
        return_value={"success": True, "data": {"code": "513300", "latest_price": 2.33, "iopv": None, "discount_pct": None}},
    ), patch(
        "plugins.merged.fetch_etf_data.tool_fetch_etf_data",
        return_value={"success": True, "data": {"code": "513300", "current_price": 2.33, "amount": 80000000, "change_pct": 1.2}},
    ), patch(
        "plugins.data_collection.index.fetch_global_hist_sina.tool_fetch_global_index_hist_sina",
        return_value={"success": True, "data": [{"close": 100 + i} for i in range(40)]},
    ), patch(
        "plugins.merged.fetch_index_data.tool_fetch_index_data",
        side_effect=_mock_fetch_index_data,
    ), patch(
        "plugins.notification.run_tail_session_analysis._fetch_nq_futures_snapshot",
        return_value={"status": "ok", "symbol": "NQ=F", "change_pct": 0.5},
    ):
        rd, _errs = build_tail_session_report_data(fetch_mode="test", market_profile="nasdaq_513300")

    snap = rd.get("tail_session_snapshot") if isinstance(rd.get("tail_session_snapshot"), dict) else {}
    risk_gate = (rd.get("analysis") or {}).get("risk_gate") if isinstance(rd.get("analysis"), dict) else {}
    assert snap.get("change_pct") is not None
    assert snap.get("as_of")
    assert isinstance((rd.get("analysis") or {}).get("signal_summary"), dict)
    assert risk_gate.get("decision") in {"GO", "GO_LIGHT", "WAIT", "EXIT_REDUCE"}
    assert isinstance(risk_gate.get("reason_codes"), list)
