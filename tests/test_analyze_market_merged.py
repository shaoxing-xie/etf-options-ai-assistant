from __future__ import annotations

from unittest.mock import patch

from plugins.merged.analyze_market import tool_analyze_market


@patch("plugins.analysis.trend_analysis.tool_analyze_opening_market")
def test_tool_analyze_market_opening_routes_to_plugins_namespace(mock_opening) -> None:
    mock_opening.return_value = {"success": True, "data": {"ok": 1}}
    out = tool_analyze_market("opening")
    assert out.get("success") is True
    mock_opening.assert_called_once()
