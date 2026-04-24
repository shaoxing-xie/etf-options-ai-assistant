from __future__ import annotations

from plugins.notification.send_daily_report import _format_daily_report


def test_tail_session_report_sections() -> None:
    rd = {
        "report_type": "tail_session",
        "generated_at": "2026-04-14 14:40:00",
        "tail_session_snapshot": {
            "latest_price": 1.23,
            "iopv": 1.2,
            "premium_pct": 2.5,
            "amount": 50000000,
            "data_quality": "fresh",
            "iopv_source": "realtime",
            "valuation_blend": {
                "confidence": "medium",
                "agreement_gap_pct": 0.88,
                "futures_proxy": {"premium_rate": 2.8},
                "fundgz": {"premium_rate": 2.3},
                "chosen_value": 2.5,
            },
        },
        "analysis": {
            "index_close": 57810.8,
            "index_day_ret_pct": 2.31,
            "ma25_dev_pct": 4.8,
            "rsi14": 68.7,
            "streak_days": 2,
            "layer_outputs": [
                {"layer": "cycle", "options": ["hold", "buy_light"]},
                {"layer": "timing", "options": ["hold"], "reasons": ["未过热"]},
                {"layer": "risk", "options": ["hold", "reduce"], "gate_hits": ["premium_hard_stop"]},
            ],
            "decision_options": {
                "conservative": {"action": "hold", "max_position_pct": 20},
                "neutral": {"action": "hold", "max_position_pct": 40},
                "aggressive": {"action": "reduce", "max_position_pct": 60},
            },
            "risk_notices": ["当前溢价偏高，需警惕价格向IOPV回归带来的被动回撤。"],
            "user_decision_note": "本系统仅提供多视角信息，不替代你的最终交易决策。",
            "signal_board": {
                "direction_score": 2.1,
                "strength_score": 2.8,
                "confidence": 0.78,
                "futures_status": "unknown",
            },
            "risk_gate": {"quality_status": "ok", "gates_triggered": ["liquidity_guard_gate"]},
            "range_prediction": {
                "core_range": [1.21, 1.25],
                "safe_range": [1.20, 1.26],
                "core_width_pct": 3.2,
                "safe_width_pct": 4.1,
            },
            "monitor_projection": {
                "projection_label": "午盘开盘区间",
                "key_levels": [
                    {"name": "afternoon_open_low", "value": 1.2123},
                    {"name": "afternoon_open_high", "value": 1.2478},
                ],
            },
            "premium_percentile_20d": 78.2,
            "deviation_percentile_20d": 84.1,
            "temperature_band": "warm",
            "temperature_position_ceiling": 0.5,
        },
        "monitor_context": {
            "monitor_point": "M3",
            "monitor_label": "M3 早盘收官",
            "target_window": "10:30-11:30",
            "template_focus": ["收官前15分钟结构", "午盘开盘区间"],
        },
    }
    _, body = _format_daily_report(report_data=rd, report_date=None)
    assert "### 一、时点快照" in body
    assert "### 二、本时点模板焦点" in body
    assert "### 三、区间预测（操作参考主轴）" in body
    assert "### 四、偏离代理与门禁" in body
    assert "### 六、简版操作建议" in body
    assert "### 七、用户决策声明" in body
    assert "IOPV来源：realtime" in body
    assert "双源估值：置信度" in body
    assert "历史分位：溢价" in body
