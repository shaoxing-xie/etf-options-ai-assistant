from __future__ import annotations

from plugins.notification.send_daily_report import _format_daily_report


def test_opening_report_uses_six_section_structure_without_northbound() -> None:
    rd = {
        "report_type": "opening",
        "opening_report_variant": "realtime",
        "generated_at": "2026-05-01 21:20:00",
        "runtime_context": {"is_opening_window": False, "snapshot_time": "2026-05-01 21:20:00"},
        "analysis": {"overall_trend": "偏强", "trend_strength": 0.8},
        "opening_market_snapshot": {
            "indices_realtime": [{"name": "沪深300", "price": 4500, "change_pct": 0.2}],
            "etf_realtime": [{"name": "沪深300ETF", "change_pct": 0.1}],
        },
        "data_quality_flags": [{"code": "stale_data", "severity": "low"}],
        "tracked_assets_snapshot": {
            "etf": [{"name": "沪深300ETF", "strength": "强", "change_pct": 0.1}],
            "stocks": [],
        },
        "opening_flow_signals": {
            "market_breadth": {"tracked_etf_strong_count": 1, "tracked_etf_weak_count": 0, "tracked_etf_total": 1},
            "flow_bias": "偏强",
            "note": "test note",
        },
        "rotation_opening_validation": [
            {
                "rotation_rank": 1,
                "etf_code": "159997",
                "etf_name": "电子ETF",
                "rotation_score": 0.86,
                "open_change_pct": 1.2,
                "volume_ratio": 1.35,
                "signal": "STRONG",
                "signal_reason": "高开放量，动量延续",
            }
        ],
        "rotation_trading_suggestions": {
            "market_gate": "GO",
            "main_actions": [
                {
                    "etf_code": "159997",
                    "etf_name": "电子ETF",
                    "position_multiplier": 1.0,
                    "signal_reason": "高开放量，动量延续",
                }
            ],
            "observe_list": [],
            "risk_controls": ["测试风控1"],
        },
        "rotation_validation_quality": {"quality_status": "ok", "degraded_reason": "", "missing_fields": []},
        "rotation_data_freshness": {
            "rotation_trade_date": "2026-04-30",
            "opening_trade_date": "2026-05-01",
            "is_prev_trading_day": True,
            "note": "轮动数据基准：2026-04-30；开盘验证基于当日实时行情。",
        },
    }
    _title, body = _format_daily_report(report_data=rd, report_date=None)
    assert "### 一、开盘快照（竞价/开盘）" in body
    assert "### 二、板块温度（开盘前15分钟）" in body
    assert "### 三、资金与成交状态" in body
    assert "### 四、跟踪标的（ETF/股票）" in body
    assert "### 五、当日预判与执行" in body
    assert "### 六、交易阈值与风控（机构口径）" in body
    assert "### 七、轮动推荐ETF开盘验证与当日建议" in body
    assert "轮动数据基准：2026-04-30" in body
    assert "模式：** 非开盘复盘" in body
    assert "### ⚠️ 数据一致性提示" in body
    assert "板块热度为前一个交易日数据" in body
    assert "### 💹 北向资金" not in body


def test_opening_rotation_section_shows_degraded_notice() -> None:
    rd = {
        "report_type": "opening",
        "opening_report_variant": "realtime",
        "generated_at": "2026-05-01 21:20:00",
        "runtime_context": {"is_opening_window": False, "snapshot_time": "2026-05-01 21:20:00"},
        "analysis": {"overall_trend": "偏弱", "trend_strength": -0.2},
        "rotation_validation_quality": {
            "quality_status": "degraded",
            "degraded_reason": "rotation_latest_missing",
            "missing_fields": [],
        },
        "rotation_trading_suggestions": {"market_gate": "STOP", "main_actions": [], "observe_list": [], "risk_controls": []},
        "rotation_data_freshness": {
            "rotation_trade_date": "",
            "opening_trade_date": "2026-05-01",
            "is_prev_trading_day": False,
            "note": "轮动数据基准：N/A；开盘验证基于当日实时行情。",
        },
    }
    _title, body = _format_daily_report(report_data=rd, report_date=None)
    assert "### 七、轮动推荐ETF开盘验证与当日建议" in body
    assert "本栏目暂不可用（仅观察）" in body
    assert "rotation_latest_missing" in body


def test_opening_rotation_section_non_opening_window_skip_validation_notice() -> None:
    rd = {
        "report_type": "opening",
        "opening_report_variant": "realtime",
        "generated_at": "2026-05-01 21:20:00",
        "runtime_context": {"is_opening_window": False, "snapshot_time": "2026-05-01 21:20:00"},
        "analysis": {"overall_trend": "偏弱", "trend_strength": -0.2},
        "rotation_opening_validation": [
            {
                "rotation_rank": 1,
                "etf_code": "159997",
                "etf_name": "电子ETF",
                "rotation_score": 0.86,
                "open_change_pct": None,
                "volume_ratio": None,
                "signal": "OBSERVE",
                "signal_reason": "非开盘复盘：跳过开盘验证（仅展示轮动清单）",
            }
        ],
        "rotation_trading_suggestions": {"market_gate": "GO", "main_actions": [], "observe_list": [], "risk_controls": []},
        "rotation_validation_quality": {
            "quality_status": "degraded",
            "degraded_reason": "not_opening_window_skip_validation",
            "missing_fields": [],
        },
        "rotation_data_freshness": {"note": "轮动数据基准：2026-04-30；开盘验证基于当日实时行情。"},
    }
    _title, body = _format_daily_report(report_data=rd, report_date=None)
    assert "### 七、轮动推荐ETF开盘验证与当日建议" in body
    assert "非开盘复盘：跳过开盘量价验证" in body


def test_opening_legacy_report_includes_vote_evidence_and_holiday_hint() -> None:
    rd = {
        "report_type": "opening",
        "opening_report_variant": "legacy",
        "generated_at": "2026-04-30 09:20:00",
        "analysis": {"overall_trend": "偏强", "trend_strength": 0.8},
        "trend_resolution": {"local_score": 0.8, "overnight_score": -0.47, "conflict": True},
        "overnight_bias_label": "谨慎偏弱",
        "overnight_bias_vote": [
            {"strength_factor": -0.6},
            {"strength_factor": -1.0},
            {"strength_factor": -0.6},
            {"strength_factor": 0.0},
            {"strength_factor": 0.0},
        ],
        "holiday_position_hint": {"enabled": True, "non_trading_days_ahead": 5, "bias_label": "谨慎偏弱"},
        "policy_event_quality": {"quality_status": "degraded", "degraded_reason": "policy_events_not_structured"},
        "tool_compute_index_key_levels": {
            "success": True,
            "data": {
                "index_code": "000300",
                "last_close": 4629.9395,
                "support": [4600],
                "resistance": [4700, 4733.75, 4790.69],
            },
        },
    }
    _title, body = _format_daily_report(report_data=rd, report_date=None)
    assert "### 结论依据（多空投票）" in body
    assert "### 📅 节前持仓提示" in body
    assert "政策事件结构化为 degraded" in body
    assert "适用指数：沪深300（000300，关键位按日线近似计算）" in body

