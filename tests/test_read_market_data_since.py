"""Contract: since floors start_date for daily read path."""

from unittest.mock import patch

from plugins.merged.read_market_data import tool_read_market_data


def test_tool_read_market_data_since_floors_start():
    captured = {}

    def _fake_read_cache_data(**kwargs):
        captured.update(kwargs)
        return {"success": True, "message": "ok", "data": {"records": [], "count": 0}}

    with patch("data_access.read_cache_data.read_cache_data", side_effect=_fake_read_cache_data):
        tool_read_market_data(
            data_type="index_daily",
            symbol="000300",
            start_date="20200101",
            end_date="20251231",
            since="20240101",
        )
    assert captured.get("start_date") == "20240101"
    assert captured.get("skip_online_refill") is True
