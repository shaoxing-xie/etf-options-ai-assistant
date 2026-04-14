"""tool_run_signal_risk_inspection_and_send / build_inspection_report."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

SH_TZ = timezone(timedelta(hours=8))


def test_build_inspection_report_non_trading_degraded() -> None:
    from plugins.notification.run_signal_risk_inspection import build_inspection_report

    with patch("plugins.utils.trading_day.is_trading_day", return_value=False):
        r = build_inspection_report(phase="afternoon", fetch_mode="production")
    assert r["market_state"] == "非交易日"
    assert r["next_update"] == "下一交易日"
    assert r["hs300_change"] == "数据不足"
    # 任意字段含数据不足 → send 层会标 data_source_degraded
    assert "数据不足" in r["var_snapshot"]


@patch("plugins.notification.send_dingtalk_message.tool_send_dingtalk_message")
def test_tool_run_signal_risk_inspection_and_send_mock_trading(mock_dt: MagicMock) -> None:
    mock_dt.return_value = {
        "success": True,
        "message": "skipped",
        "delivery": {"ok": True, "errcode": 0},
        "data": {},
    }

    idx_data = [
        {
            "code": "000300",
            "name": "沪深300",
            "current_price": 4000.0,
            "change_percent": 0.5,
            "prev_close": 3980.0,
            "high": 4010.0,
            "low": 3970.0,
        },
        {
            "code": "399006",
            "name": "创业板指",
            "current_price": 2500.0,
            "change_percent": -0.2,
            "prev_close": 2505.0,
            "high": 2510.0,
            "low": 2490.0,
        },
        {
            "code": "000905",
            "name": "中证500",
            "current_price": 6000.0,
            "change_percent": 0.1,
            "prev_close": 5994.0,
            "high": 6010.0,
            "low": 5980.0,
        },
    ]
    etf_data = [
        {
            "code": "510300",
            "found": True,
            "current_price": 4.0,
            "change_percent": 0.5,
            "high": 4.02,
            "low": 3.98,
        },
        {
            "code": "510500",
            "found": True,
            "current_price": 6.0,
            "change_percent": 0.2,
            "high": 6.05,
            "low": 5.95,
        },
        {
            "code": "159915",
            "found": True,
            "current_price": 2.0,
            "change_percent": -0.1,
            "high": 2.02,
            "low": 1.98,
        },
    ]
    pr_data = {
        "var_historical_pct": 1.23,
        "max_drawdown_pct": -5.5,
        "current_drawdown_pct": -1.1,
        "current_position_pct": 55.0,
        "position_risk_flag": "ok",
        "drawdown_risk_flag": "ok",
    }

    with patch("plugins.utils.trading_day.is_trading_day", return_value=True):
        with patch("plugins.merged.fetch_index_data.tool_fetch_index_data") as m_idx:
            with patch("plugins.merged.fetch_etf_data.tool_fetch_etf_data") as m_etf:
                with patch("plugins.risk.portfolio_risk_snapshot.tool_portfolio_risk_snapshot") as m_pr:
                    m_idx.return_value = {"success": True, "data": idx_data}
                    m_etf.return_value = {"success": True, "data": etf_data}
                    m_pr.return_value = {"success": True, "data": pr_data}
                    with patch(
                        "plugins.analysis.intraday_range.tool_predict_intraday_range",
                        return_value={"success": False},
                    ):
                        with patch(
                            "plugins.analysis.technical_indicators.tool_calculate_technical_indicators",
                            return_value={"success": False},
                        ):
                            from plugins.notification.run_signal_risk_inspection import (
                                tool_run_signal_risk_inspection_and_send,
                            )

                            out = tool_run_signal_risk_inspection_and_send(
                                phase="midday", mode="test", fetch_mode="production"
                            )

    assert out.get("success") is True
    rendered = (out.get("data") or {}).get("rendered_message") or ""
    assert "【宽基ETF巡检快报】" in rendered
    assert "INSPECTION_RUN_STATUS:" in rendered
    assert "0.50%" in rendered or "0.5" in rendered


def test_build_inspection_report_pre_open_not_close() -> None:
    """凌晨/盘前不得误判为「收盘」；见 run_signal_risk_inspection 时段划分。"""
    from plugins.notification import run_signal_risk_inspection as m

    fixed = datetime(2026, 4, 13, 5, 58, tzinfo=SH_TZ)
    idx_data = [
        {"code": "000300", "change_percent": 1.0, "current_price": 4000.0, "prev_close": 3960.0},
        {"code": "399006", "change_percent": 1.0, "current_price": 2500.0, "prev_close": 2480.0},
        {"code": "000905", "change_percent": 1.0, "current_price": 6000.0, "prev_close": 5940.0},
    ]
    etf_data = [
        {"code": "510300", "found": True, "current_price": 4.0, "change_percent": 1.0, "high": 4.1, "low": 3.9},
        {"code": "510500", "found": True, "current_price": 6.0, "change_percent": 1.0, "high": 6.1, "low": 5.9},
        {"code": "159915", "found": True, "current_price": 2.0, "change_percent": 1.0, "high": 2.1, "low": 1.9},
    ]
    pr_data = {
        "var_historical_pct": 1.0,
        "max_drawdown_pct": -5.0,
        "current_drawdown_pct": -1.0,
        "current_position_pct": 45.0,
        "position_risk_flag": "ok",
        "drawdown_risk_flag": "ok",
    }

    with patch.object(m, "_now_sh", return_value=fixed):
        with patch("plugins.utils.trading_day.is_trading_day", return_value=True):
            with patch("plugins.merged.fetch_index_data.tool_fetch_index_data") as m_idx:
                with patch("plugins.merged.fetch_etf_data.tool_fetch_etf_data") as m_etf:
                    with patch("plugins.risk.portfolio_risk_snapshot.tool_portfolio_risk_snapshot") as m_pr:
                        m_idx.return_value = {"success": True, "data": idx_data}
                        m_etf.return_value = {"success": True, "data": etf_data}
                        m_pr.return_value = {"success": True, "data": pr_data}
                        with patch(
                            "plugins.analysis.intraday_range.tool_predict_intraday_range",
                            return_value={"success": False},
                        ):
                            from plugins.notification.run_signal_risk_inspection import build_inspection_report

                            r = build_inspection_report(phase="midday", fetch_mode="production")

    assert r["remain_window"] == "盘前"
    assert r["market_state"] == "pre_open"
    assert "收盘" not in r["next_update"]
    assert "约30分钟后" not in r["next_update"]


def test_tool_runner_resolves_composite() -> None:
    from tool_runner import TOOL_MAP

    assert "tool_run_signal_risk_inspection_and_send" in TOOL_MAP
    spec = TOOL_MAP["tool_run_signal_risk_inspection_and_send"]
    assert spec.module_path == "notification.run_signal_risk_inspection"
    assert spec.function_name == "tool_run_signal_risk_inspection_and_send"
