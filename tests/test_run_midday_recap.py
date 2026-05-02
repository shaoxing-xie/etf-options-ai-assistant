from __future__ import annotations

from unittest.mock import patch


def _mock_idx_ok(**kwargs: object) -> dict:
    if kwargs.get("data_type") == "realtime":
        code = str(kwargs.get("index_code") or "")
        return {"success": True, "data": {"code": code, "change_percent": 0.12}}
    return {"success": True, "data": {}}


def _mock_idx_missing_change(**kwargs: object) -> dict:
    if kwargs.get("data_type") == "realtime":
        code = str(kwargs.get("index_code") or "")
        return {"success": True, "data": {"code": code}}
    return {"success": True, "data": {}}


def _mock_idx_flat(**kwargs: object) -> dict:
    if kwargs.get("data_type") == "realtime":
        code = str(kwargs.get("index_code") or "")
        return {"success": True, "data": {"code": code, "change_percent": -0.05}}
    return {"success": True, "data": {}}


def _build_tools(
    idx_fn,
    *,
    heat_resp: dict | None = None,
    etf_resp: dict | None = None,
    risk_resp: dict | None = None,
) -> dict:
    def _heat() -> dict:
        return heat_resp or {"success": True, "sectors": []}

    def _etf(**_kwargs: object) -> dict:
        return etf_resp or {"success": True, "data": {"code": "510300"}}

    def _risk() -> dict:
        return risk_resp or {"success": True, "data": {}}

    return {
        "tool_fetch_index_data": idx_fn,
        "tool_sector_heat_score": _heat,
        "tool_fetch_etf_data": _etf,
        "tool_portfolio_risk_snapshot": _risk,
    }


@patch("plugins.notification.run_midday_recap._try_fetch_fund_flow", return_value={"ok": False})
@patch("plugins.notification.run_midday_recap._load_midday_tools")
def test_midday_analysis_health_ok(_m_tools, _m_ff) -> None:
    from plugins.notification.run_midday_recap import build_midday_recap_report_data

    _m_tools.return_value = _build_tools(_mock_idx_ok)
    rd, _errs = build_midday_recap_report_data(fetch_mode="test")
    ah = rd.get("analysis_health")
    assert isinstance(ah, dict)
    assert ah.get("status") == "ok"
    assert rd.get("run_quality") in {"ok_full", "ok_degraded"}


@patch("plugins.notification.run_midday_recap._try_fetch_fund_flow", return_value={"ok": False})
@patch("plugins.notification.run_midday_recap._load_midday_tools")
def test_midday_analysis_health_degraded_when_index_change_missing(_m_tools, _m_ff) -> None:
    from plugins.notification.run_midday_recap import build_midday_recap_report_data

    _m_tools.return_value = _build_tools(_mock_idx_missing_change)
    rd, _errs = build_midday_recap_report_data(fetch_mode="test")
    ah = rd.get("analysis_health")
    assert isinstance(ah, dict)
    assert ah.get("status") == "degraded"
    assert "midday_index_snapshot_incomplete" in str(ah.get("reason") or "")
    assert rd.get("run_quality") == "ok_degraded"


@patch(
    "plugins.notification.run_midday_recap._try_fetch_fund_flow",
    return_value={
        "ok": True,
        "industry_ths": {
            "status": "success",
            "date": "2026-04-30",
            "source": "tool_fetch_a_share_fund_flow:sector_rank",
            "data": [],
        },
    },
)
@patch("plugins.notification.run_midday_recap._load_midday_tools")
def test_midday_fund_flow_empty_data_and_sector_staleness_note(_m_tools, _m_ff) -> None:
    from plugins.notification.run_midday_recap import build_midday_recap_report_data

    _m_tools.return_value = _build_tools(
        _mock_idx_flat,
        heat_resp={"success": True, "as_of": "2026-04-29", "sectors": [{"name": "半导体", "score": 40}]},
        etf_resp={"success": True, "data": {"code": "510300", "amount": 3000000000}},
    )
    rd, _errs = build_midday_recap_report_data(fetch_mode="test")
    mr = rd.get("midday_recap")
    assert isinstance(mr, dict)
    assert mr.get("fund_flow_status") == "empty_data"
    assert "暂无可解析数据" in str(mr.get("fund_flow_data_note") or "")
    assert "非当日盘中实时快照" in str(mr.get("sector_data_note") or "")


@patch(
    "plugins.notification.run_midday_recap._try_fetch_fund_flow",
    return_value={
        "ok": True,
        "cache_used": True,
        "cache_time": "2026-04-30 11:31:30",
        "industry_ths": {
            "status": "success",
            "source": "tool_fetch_a_share_fund_flow:sector_rank (cache)",
            "data": [{"sector_name": "房地产开", "net_inflow": 10.0}],
        },
    },
)
@patch("plugins.notification.run_midday_recap._load_midday_tools")
def test_midday_fund_flow_cache_fallback_status(_m_tools, _m_ff) -> None:
    from plugins.notification.run_midday_recap import build_midday_recap_report_data

    _m_tools.return_value = _build_tools(_mock_idx_ok)
    rd, _errs = build_midday_recap_report_data(fetch_mode="test")
    mr = rd.get("midday_recap")
    assert isinstance(mr, dict)
    assert mr.get("fund_flow_status") == "cache_fallback"
    lines = mr.get("fund_flow_summary_lines")
    assert isinstance(lines, list)
    assert any("最近成功缓存" in str(x) for x in lines)


@patch(
    "plugins.notification.run_midday_recap._try_fetch_fund_flow",
    return_value={"ok": False, "industry_ths_error": "timeout"},
)
@patch("plugins.notification.send_dingtalk_message.tool_send_dingtalk_message")
@patch("plugins.notification.run_midday_recap._load_midday_tools")
def test_midday_message_contains_data_basis_line(
    _m_tools, _m_sender, _m_ff
) -> None:
    from plugins.notification.run_midday_recap import tool_run_midday_recap_and_send

    _m_tools.return_value = _build_tools(
        _mock_idx_flat,
        etf_resp={"success": True, "data": {"code": "510300", "amount": 2800000000}},
    )
    _m_sender.return_value = {"success": True, "data": {"delivery": {"ok": True}}}
    tool_run_midday_recap_and_send(mode="test", fetch_mode="test")
    _, kwargs = _m_sender.call_args
    message = str(kwargs.get("message") or "")
    assert "行情口径" in message
    assert "指数=盘中实时" in message
