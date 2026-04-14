from __future__ import annotations

from plugins.notification.send_daily_report import _format_daily_report


def test_opening_report_uses_six_section_structure_without_northbound() -> None:
    rd = {
        "report_type": "opening",
        "opening_report_variant": "realtime",
        "generated_at": "2026-04-14 09:20:00",
        "runtime_context": {"is_opening_window": True, "snapshot_time": "2026-04-14 09:20:00"},
        "analysis": {"overall_trend": "偏强", "trend_strength": 0.8},
        "opening_market_snapshot": {
            "indices_realtime": [{"name": "沪深300", "price": 4500, "change_pct": 0.2}],
            "etf_realtime": [{"name": "沪深300ETF", "change_pct": 0.1}],
        },
        "tracked_assets_snapshot": {
            "etf": [{"name": "沪深300ETF", "strength": "强", "change_pct": 0.1}],
            "stocks": [],
        },
        "opening_flow_signals": {
            "market_breadth": {"tracked_etf_strong_count": 1, "tracked_etf_weak_count": 0, "tracked_etf_total": 1},
            "flow_bias": "偏强",
            "note": "test note",
        },
    }
    _title, body = _format_daily_report(report_data=rd, report_date=None)
    assert "### 一、开盘快照（竞价/开盘）" in body
    assert "### 二、板块温度（开盘前15分钟）" in body
    assert "### 三、资金与成交状态" in body
    assert "### 四、跟踪标的（ETF/股票）" in body
    assert "### 五、当日预判与执行" in body
    assert "### 六、交易阈值与风控（机构口径）" in body
    assert "### 💹 北向资金" not in body

