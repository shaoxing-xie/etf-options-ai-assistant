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


@patch("plugins.notification.run_midday_recap._try_fetch_fund_flow", return_value={"ok": False})
@patch("plugins.risk.portfolio_risk_snapshot.tool_portfolio_risk_snapshot", return_value={"success": True, "data": {}})
@patch("plugins.merged.fetch_etf_data.tool_fetch_etf_data", return_value={"success": True, "data": {"code": "510300"}})
@patch("plugins.data_collection.limit_up.sector_heat.tool_sector_heat_score", return_value={"success": True, "sectors": []})
@patch("plugins.merged.fetch_index_data.tool_fetch_index_data", side_effect=_mock_idx_ok)
def test_midday_analysis_health_ok(
    _m_idx, _m_heat, _m_etf, _m_risk, _m_ff
) -> None:
    from plugins.notification.run_midday_recap import build_midday_recap_report_data

    rd, _errs = build_midday_recap_report_data(fetch_mode="test")
    ah = rd.get("analysis_health")
    assert isinstance(ah, dict)
    assert ah.get("status") == "ok"
    assert rd.get("run_quality") in {"ok_full", "ok_degraded"}


@patch("plugins.notification.run_midday_recap._try_fetch_fund_flow", return_value={"ok": False})
@patch("plugins.risk.portfolio_risk_snapshot.tool_portfolio_risk_snapshot", return_value={"success": True, "data": {}})
@patch("plugins.merged.fetch_etf_data.tool_fetch_etf_data", return_value={"success": True, "data": {"code": "510300"}})
@patch("plugins.data_collection.limit_up.sector_heat.tool_sector_heat_score", return_value={"success": True, "sectors": []})
@patch("plugins.merged.fetch_index_data.tool_fetch_index_data", side_effect=_mock_idx_missing_change)
def test_midday_analysis_health_degraded_when_index_change_missing(
    _m_idx, _m_heat, _m_etf, _m_risk, _m_ff
) -> None:
    from plugins.notification.run_midday_recap import build_midday_recap_report_data

    rd, _errs = build_midday_recap_report_data(fetch_mode="test")
    ah = rd.get("analysis_health")
    assert isinstance(ah, dict)
    assert ah.get("status") == "degraded"
    assert "midday_index_snapshot_incomplete" in str(ah.get("reason") or "")
    assert rd.get("run_quality") == "ok_degraded"
