"""契约形状：高频工具返回体与 data/meta/error_codes.yaml 约定对齐（默认 fixture，不依赖在线插件）。"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _read_error_codes() -> dict:
    p = ROOT / "data" / "meta" / "error_codes.yaml"
    assert p.is_file(), "data/meta/error_codes.yaml must exist"
    import yaml  # type: ignore

    return yaml.safe_load(p.read_text(encoding="utf-8"))


def test_error_codes_yaml_has_core_codes() -> None:
    doc = _read_error_codes()
    codes = (doc or {}).get("error_codes") or {}
    for key in ("UPSTREAM_FETCH_FAILED", "NO_DATA", "INVALID_PARAMS"):
        assert key in codes, f"missing error_codes.{key}"
    qs = (doc or {}).get("quality_status") or {}
    assert "enum" in qs
    assert set(qs["enum"]) >= {"ok", "degraded", "error"}


def test_read_market_data_contract_fixture() -> None:
    """模拟 tool_read_market_data 成功/失败最小形状。"""
    ok_payload = {
        "success": True,
        "data": {"rows": []},
        "_meta": {"quality_status": "ok", "schema_name": "x", "schema_version": "1"},
    }
    assert ok_payload["_meta"].get("quality_status") == "ok"
    bad = {
        "success": False,
        "error_code": "NO_DATA",
        "quality_status": "error",
        "message": "empty",
    }
    assert bad["error_code"] in _read_error_codes()["error_codes"]


def test_tool_read_market_data_missing_data_type_returns_meta() -> None:
    from plugins.merged.read_market_data import tool_read_market_data

    r = tool_read_market_data()
    assert r.get("success") is False
    assert r.get("error_code") == "INVALID_PARAMS"
    meta = r.get("_meta") or {}
    assert meta.get("quality_status") == "error"
    assert meta.get("schema_name") == "tool_read_market_data"


def test_tool_read_market_data_success_gets_meta_ok() -> None:
    from unittest.mock import patch

    from plugins.merged.read_market_data import tool_read_market_data

    fake = {"success": True, "message": "cache hit", "data": {"records": [], "count": 0}, "source": "cache"}

    with patch("data_access.read_cache_data.read_cache_data", return_value=fake):
        r = tool_read_market_data(data_type="index_daily", symbol="000300", start_date="20200101", end_date="20200131")
    assert r.get("success") is True
    meta = r.get("_meta") or {}
    assert meta.get("quality_status") == "ok"
    assert meta.get("schema_name") == "tool_read_market_data"


def test_index_historical_tool_shape_fixture() -> None:
    """与 plugins.data_collection.index.fetch_historical 单指数成功体一致。"""
    fixture = {
        "success": True,
        "message": "ok",
        "data": {
            "index_code": "000300",
            "index_name": "沪深300",
            "period": "daily",
            "klines": [
                {
                    "date": "2026-01-02",
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.05,
                    "volume": 100.0,
                    "amount": 1000.0,
                    "change_percent": 0.1,
                }
            ],
            "count": 1,
        },
        "source": "tushare",
    }
    assert fixture["success"] is True
    k = fixture["data"]["klines"][0]
    for fld in ("date", "open", "close", "volume"):
        assert fld in k


@pytest.mark.integration
def test_merged_tool_fetch_index_data_importable() -> None:
    """integration：仅校验合并工具可导入（不强制联网成功）。"""
    from plugins.merged.fetch_index_data import tool_fetch_index_data

    assert callable(tool_fetch_index_data)
