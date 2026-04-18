"""before_open 报告格式回归：标题与时间锚。"""

from __future__ import annotations

from plugins.notification.send_daily_report import _format_daily_report


def test_before_open_title_without_date_suffix_and_use_generated_at() -> None:
    rd = {
        "report_type": "before_open",
        "date": "2026-04-13",
        "generated_at": "2026-04-13 09:20:00",
        "analysis": {"overall_trend": "偏强", "trend_strength": 0.8},
    }
    title, body = _format_daily_report(report_data=rd, report_date=None)
    assert title == "开盘前市场趋势分析报告"
    assert "**分析时间：** 2026-04-13 09:20:00" in body


def test_before_open_regime_note_no_double_bullet() -> None:
    rd = {
        "report_type": "before_open",
        "generated_at": "2026-04-13 09:20:00",
        "a_share_regime_note": "- 收盘后：连续竞价已结束。",
        "analysis": {"overall_trend": "偏强", "trend_strength": 0.8},
    }
    _title, body = _format_daily_report(report_data=rd, report_date=None)
    assert "\n- - 收盘后：" not in body
    assert "- 收盘后：连续竞价已结束。" in body


def test_before_open_non_intraday_uses_next_day_anchors_and_hxc_copy() -> None:
    rd = {
        "report_type": "before_open",
        "generated_at": "2026-04-13 15:35:00",
        "a_share_regime_note": "- 收盘后：连续竞价已结束。",
        "analysis": {
            "overall_trend": "震荡",
            "trend_strength": 0.5,
            "hxc_change": None,
            "hxc_status": "error",
            "hxc_reason": "历史数据为空",
            "a50_change": None,
        },
    }
    _title, body = _format_daily_report(report_data=rd, report_date=None)
    assert "### 次日时间锚点（非连续竞价时段）" in body
    assert "### 盘中时间锚点" not in body
    assert "- **纳斯达克中国金龙：** 接口异常" in body


def test_before_open_uses_readable_sections_for_regime_links_and_nb() -> None:
    rd = {
        "report_type": "before_open",
        "generated_at": "2026-04-13 09:20:00",
        "a_share_regime_note": "- 收盘后：连续竞价已结束。",
        "policy_news": {
            "brief_answer": "Based on the most recent data, this is english.",
            "items": [
                {"title": "5%→10%！A股交易规则，拟调整！", "url": "https://example.com/a"},
                {"title": "国务院减轻企业负担部际联席会议召开", "url": "https://example.com/b"},
            ],
        },
        "analysis": {"overall_trend": "震荡", "trend_strength": 0.5},
        "overnight_digest": {
            "evidence_urls": [
                "https://a.com/1",
                "https://a.com/2",
            ]
        },
    }
    _title, body = _format_daily_report(report_data=rd, report_date=None)
    assert "### ⏰ 时段与口径" in body
    assert "- - 收盘后" not in body
    assert "### 🔗 参考链接" in body
    assert "- 1. https://a.com/1" in body
    assert "### 💹 北向资金" not in body

