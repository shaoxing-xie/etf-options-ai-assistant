from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from plugins.analysis.rotation_data_health import tool_rotation_data_health_check


def test_rotation_data_health_check_structure() -> None:
    def _fake_read_cache_data(**kwargs):
        sym = kwargs.get("symbol")
        if str(sym).endswith("0"):
            return {"success": True, "message": "cache hit", "df": [1, 2, 3], "missing_dates": []}
        return {"success": False, "message": "miss", "df": None, "missing_dates": ["20260101"]}

    def _fake_fetch_single_etf_historical(**kwargs):
        code = str(kwargs.get("etf_code"))
        if code.endswith("0"):
            return [1, 2, 3, 4], "tushare"
        return None, "eastmoney"

    fake_module = SimpleNamespace(fetch_single_etf_historical=_fake_fetch_single_etf_historical)
    # read_cache_data and importlib are resolved inside tool function.
    with patch("plugins.analysis.rotation_data_health.read_cache_data", side_effect=_fake_read_cache_data), patch(
        "plugins.analysis.rotation_data_health.importlib.import_module",
        return_value=fake_module,
    ):
        out = tool_rotation_data_health_check(symbols="512480,513120", lookback_days=30)
    assert out["success"] is True
    data = out["data"]
    assert "industry_coverage" in data and "concept_coverage" in data
    assert isinstance(data["records"], list)
    assert isinstance(data["degraded_evidence"], list)
    assert all("retry_attempts" in x for x in data["degraded_evidence"])
