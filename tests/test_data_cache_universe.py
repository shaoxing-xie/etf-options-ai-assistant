"""data_cache 标的清单：轮动池合并逻辑。"""

from __future__ import annotations

from unittest.mock import patch

from src.data_cache_universe import _merge_rotation_etf_codes_into, get_data_cache_universe


def test_merge_rotation_etf_codes_appends_missing() -> None:
    with (
        patch("analysis.etf_rotation_core.resolve_etf_pool", return_value=["512100", "512880"]),
        patch("src.rotation_config_loader.load_rotation_config", return_value={}),
    ):
        merged = _merge_rotation_etf_codes_into(["510300"])
    assert merged[:1] == ["510300"]
    assert "512100" in merged
    assert "512880" in merged


def test_get_data_cache_universe_merges_rotation() -> None:
    cfg = {
        "data_cache": {
            "index_codes": ["000300"],
            "etf_codes": ["510300"],
            "stock_codes": [],
        }
    }
    with (
        patch("analysis.etf_rotation_core.resolve_etf_pool", return_value=["512100"]),
        patch("src.rotation_config_loader.load_rotation_config", return_value={}),
    ):
        u = get_data_cache_universe(cfg)
    assert "510300" in u["etf_codes"]
    assert "512100" in u["etf_codes"]
