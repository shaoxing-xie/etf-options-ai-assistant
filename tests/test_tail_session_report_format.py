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
        },
    }
    _, body = _format_daily_report(report_data=rd, report_date=None)
    assert "### 一、尾盘快照" in body
    assert "### 三、分层建议（不合成单一结论）" in body
    assert "### 四、用户可选路径" in body
    assert "### 五、风险提示与执行摩擦" in body
    assert "### 六、用户决策声明" in body
    assert "IOPV来源：realtime" in body
