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


def test_build_inspection_report_after_close_next_update_next_trading_day() -> None:
    from plugins.notification import run_signal_risk_inspection as m

    fixed = datetime(2026, 4, 14, 20, 5, tzinfo=SH_TZ)
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
            with patch("plugins.merged.fetch_index_data.tool_fetch_index_data", return_value={"success": True, "data": idx_data}):
                with patch("plugins.merged.fetch_etf_data.tool_fetch_etf_data", return_value={"success": True, "data": etf_data}):
                    with patch("plugins.risk.portfolio_risk_snapshot.tool_portfolio_risk_snapshot", return_value={"success": True, "data": pr_data}):
                        r = m.build_inspection_report(phase="afternoon", fetch_mode="test")

    assert r["market_state"] == "after_close"
    assert r["remain_window"] == "收盘"
    assert r["next_update"] == "下一交易日"


def test_tool_runner_resolves_composite() -> None:
    from tool_runner import TOOL_MAP

    assert "tool_run_signal_risk_inspection_and_send" in TOOL_MAP
    spec = TOOL_MAP["tool_run_signal_risk_inspection_and_send"]
    assert spec.module_path == "notification.run_signal_risk_inspection"
    assert spec.function_name == "tool_run_signal_risk_inspection_and_send"


def test_build_inspection_report_debug_force_tail_section_outside_trading() -> None:
    from plugins.notification import run_signal_risk_inspection as m

    fixed = datetime(2026, 4, 13, 21, 30, tzinfo=SH_TZ)  # 夜间，非交易时段
    idx_data = [
        {"code": "000300", "change_percent": 0.5, "current_price": 4000.0, "prev_close": 3980.0},
        {"code": "399006", "change_percent": 1.2, "current_price": 2500.0, "prev_close": 2470.0},
        {"code": "000905", "change_percent": 0.6, "current_price": 6000.0, "prev_close": 5964.0},
    ]
    etf_data = [
        {"code": "510300", "found": True, "current_price": 4.0, "change_percent": 0.5, "high": 4.1, "low": 3.9},
        {"code": "510500", "found": True, "current_price": 6.0, "change_percent": 0.2, "high": 6.1, "low": 5.9},
        {"code": "159915", "found": True, "current_price": 2.0, "change_percent": 1.7, "high": 2.1, "low": 1.9},
    ]
    pr_data = {
        "var_historical_pct": 1.2,
        "max_drawdown_pct": -5.5,
        "current_drawdown_pct": -1.5,
        "current_position_pct": 45.0,
        "position_risk_flag": "ok",
        "drawdown_risk_flag": "ok",
    }

    with patch.object(m, "_now_sh", return_value=fixed):
        with patch("plugins.utils.trading_day.is_trading_day", return_value=False):
            with patch("plugins.merged.fetch_index_data.tool_fetch_index_data", return_value={"success": True, "data": idx_data}):
                with patch("plugins.merged.fetch_etf_data.tool_fetch_etf_data", return_value={"success": True, "data": etf_data}):
                    with patch("plugins.risk.portfolio_risk_snapshot.tool_portfolio_risk_snapshot", return_value={"success": True, "data": pr_data}):
                        r = m.build_inspection_report(
                            phase="afternoon",
                            fetch_mode="test",
                            debug_force_tail_section=True,
                            debug_now="2026-04-13 21:30:00",
                        )

    assert r.get("tail_section_enabled") is True
    assert isinstance(r.get("tail_advice"), dict)
    assert r.get("tail_time_gate") == "debug_forced"


def test_build_inspection_report_before_14_no_tail_section() -> None:
    from plugins.notification import run_signal_risk_inspection as m

    fixed = datetime(2026, 4, 14, 13, 50, tzinfo=SH_TZ)
    idx_data = [
        {"code": "000300", "change_percent": 0.4, "current_price": 4000.0, "prev_close": 3984.0},
        {"code": "399006", "change_percent": 0.6, "current_price": 2500.0, "prev_close": 2485.0},
        {"code": "000905", "change_percent": 0.3, "current_price": 6000.0, "prev_close": 5982.0},
    ]
    etf_data = [
        {"code": "510300", "found": True, "current_price": 4.0, "change_percent": 0.5, "high": 4.1, "low": 3.9},
        {"code": "510500", "found": True, "current_price": 6.0, "change_percent": 0.2, "high": 6.1, "low": 5.9},
        {"code": "159915", "found": True, "current_price": 2.0, "change_percent": 0.7, "high": 2.1, "low": 1.9},
    ]
    pr_data = {
        "var_historical_pct": 1.2,
        "max_drawdown_pct": -4.0,
        "current_drawdown_pct": -1.2,
        "current_position_pct": 45.0,
        "position_risk_flag": "ok",
        "drawdown_risk_flag": "ok",
    }
    with patch.object(m, "_now_sh", return_value=fixed):
        with patch("plugins.utils.trading_day.is_trading_day", return_value=True):
            with patch("plugins.merged.fetch_index_data.tool_fetch_index_data", return_value={"success": True, "data": idx_data}):
                with patch("plugins.merged.fetch_etf_data.tool_fetch_etf_data", return_value={"success": True, "data": etf_data}):
                    with patch("plugins.risk.portfolio_risk_snapshot.tool_portfolio_risk_snapshot", return_value={"success": True, "data": pr_data}):
                        r = m.build_inspection_report(phase="afternoon", fetch_mode="test")
    assert r.get("tail_section_enabled") is False
    assert "tail_advice" not in r


def test_build_inspection_report_after_14_has_tail_section() -> None:
    from plugins.notification import run_signal_risk_inspection as m

    fixed = datetime(2026, 4, 14, 14, 20, tzinfo=SH_TZ)
    idx_data = [
        {"code": "000300", "change_percent": 0.4, "current_price": 4000.0, "prev_close": 3984.0},
        {"code": "399006", "change_percent": 1.6, "current_price": 2500.0, "prev_close": 2461.0},
        {"code": "000905", "change_percent": 0.3, "current_price": 6000.0, "prev_close": 5982.0},
    ]
    etf_data = [
        {"code": "510300", "found": True, "current_price": 4.0, "change_percent": 0.5, "high": 4.1, "low": 3.9},
        {"code": "510500", "found": True, "current_price": 6.0, "change_percent": 0.2, "high": 6.1, "low": 5.9},
        {"code": "159915", "found": True, "current_price": 2.0, "change_percent": 1.7, "high": 2.1, "low": 1.9},
    ]
    pr_data = {
        "var_historical_pct": 1.2,
        "max_drawdown_pct": -4.0,
        "current_drawdown_pct": -1.2,
        "current_position_pct": 45.0,
        "position_risk_flag": "ok",
        "drawdown_risk_flag": "ok",
    }
    with patch.object(m, "_now_sh", return_value=fixed):
        with patch("plugins.utils.trading_day.is_trading_day", return_value=True):
            with patch("plugins.merged.fetch_index_data.tool_fetch_index_data", return_value={"success": True, "data": idx_data}):
                with patch("plugins.merged.fetch_etf_data.tool_fetch_etf_data", return_value={"success": True, "data": etf_data}):
                    with patch("plugins.risk.portfolio_risk_snapshot.tool_portfolio_risk_snapshot", return_value={"success": True, "data": pr_data}):
                        r = m.build_inspection_report(phase="afternoon", fetch_mode="test")
    assert r.get("tail_section_enabled") is True
    assert isinstance(r.get("tail_advice"), dict)
    tail = r.get("tail_advice") or {}
    assert "indicator_conclusion" in tail
    assert "next_day_basis" in tail


@patch("plugins.notification.send_dingtalk_message.tool_send_dingtalk_message")
def test_send_message_contains_tail_section_fields(mock_dt: MagicMock) -> None:
    from plugins.notification.send_signal_risk_inspection import tool_send_signal_risk_inspection

    mock_dt.return_value = {"success": True, "delivery": {"ok": True}, "data": {}}
    report = {
        "date": "2026-04-14",
        "time": "14:40",
        "time_ref": "14:40",
        "hs300_change": "0.50%",
        "hs300_strength": "偏强",
        "gem_change": "0.60%",
        "gem_strength": "偏强",
        "zz500_change": "0.40%",
        "zz500_strength": "中性",
        "style_judgment": "风格均衡",
        "510300_price": "4.000",
        "510300_change": "0.50%",
        "510300_position": "现价4.000，日内上涨0.50%",
        "510300_resist": "4.100",
        "510300_support": "3.900",
        "510500_price": "6.000",
        "510500_change": "0.20%",
        "510500_position": "现价6.000，涨跌0.20%",
        "510500_resist": "6.100",
        "510500_support": "5.900",
        "159915_price": "2.000",
        "159915_change": "1.70%",
        "159915_position": "现价2.000，涨跌1.70%",
        "159915_resist": "2.100",
        "159915_support": "1.900",
        "remain_window": "40",
        "market_state": "open",
        "focus1": "指数分化有限，关注量能持续性",
        "focus2": "创业板指与中证500相对强弱决定成长风格持续性",
        "focus3": "严控单标的回撤，遵守组合风控阈值",
        "510300_action": "持有观望",
        "510500_action": "持有观望",
        "159915_action": "持有观望",
        "risk_level": "中",
        "position_suggest": "维持计划仓位",
        "next_update": "约30分钟后（下午巡检）",
        "var_snapshot": "1.20%",
        "max_dd_snapshot": "-4.00%",
        "current_dd_snapshot": "-1.20%",
        "position_risk_snapshot": "45% / ok",
        "tail_section_enabled": True,
        "tail_advice": {
            "next_day_basis": "结合当日结构与隔夜变量进行次日预判。",
            "trend": {"action": "持有", "reason": "趋势偏强。", "basis": "核心指数均值变动 0.50%"},
            "timing": {"action": "减仓", "reason": "短线偏热。", "basis": "过热阈值 1.50%，当前命中=True"},
            "risk": {"action": "持有", "reason": "风险中性。", "basis": "VaR阈值 2.00/2.50%，回撤阈值 -5.00/-10.00%"},
            "indicator_conclusion": "短线偏热，当前以持有/减仓为主。",
            "overnight_refs": [{"name": "A50夜盘", "status": "unavailable"}],
            "degrade_reason": "隔夜变量部分缺失，已降级。",
            "paths": {
                "conservative": {"action": "持有", "cap": "20%"},
                "neutral": {"action": "持有", "cap": "40%"},
                "aggressive": {"action": "持有", "cap": "60%"},
            },
            "next_focus": ["A50期货夜盘方向", "晚间重大政策/事件", "隔夜美股与中概指数波动"],
        },
    }
    out = tool_send_signal_risk_inspection(report=report, phase="afternoon", mode="test")
    rendered = ((out.get("data") or {}).get("rendered_message") or "")
    assert "五、尾盘操作建议（基于次日预判）" in rendered
    assert "| 次日预判逻辑 | 结合当日结构与隔夜变量进行次日预判。 |" in rendered
    assert rendered.find("| 次日预判逻辑 |") < rendered.find("| 项目 | 内容 |")
    assert "指标结论" in rendered
    assert "隔夜变量可用性" in rendered
    assert "降级说明" in rendered
