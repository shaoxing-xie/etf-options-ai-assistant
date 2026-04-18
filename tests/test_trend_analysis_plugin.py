"""trend_analysis 插件：配置合并、简化开盘、report_meta、落盘子目录（无网络）。"""

from __future__ import annotations

from unittest.mock import patch

from plugins.analysis import trend_analysis as ta


def test_merge_trend_plugin_config_defaults():
    cfg = ta._merge_trend_plugin_config(None)
    assert cfg["enabled"] is True
    assert cfg["overlay"].get("global_index_enabled") is True
    assert "adx_index" in cfg["overlay"]
    assert cfg["fallback"]["use_simple_opening"] is True


def test_merge_trend_plugin_config_partial_overlay():
    cfg = ta._merge_trend_plugin_config(
        {"trend_analysis_plugin": {"overlay": {"adx_enabled": False}}}
    )
    assert cfg["overlay"]["adx_enabled"] is False
    assert cfg["overlay"].get("sector_heat_enabled") is True


def test_simple_opening_analysis_summary_fields():
    opening = [
        {"code": "000001", "name": "上证", "change_pct": 0.8, "volume": 1e9, "timestamp": "t1"},
        {"code": "399006", "name": "创业板", "change_pct": -0.5, "volume": 5e8, "timestamp": "t1"},
    ]
    with patch("src.data_collector.fetch_index_opening_history", return_value=None):
        with patch(
            "plugins.data_collection.limit_up.sector_heat.tool_sector_heat_score",
            return_value={"success": False},
        ):
            out = ta._simple_opening_analysis(opening, config={})

    assert "summary" in out
    assert "000001" in out and "399006" in out
    s = out["summary"]
    assert "equal_weighted_sentiment" in s
    assert "volume_weighted_sentiment" in s
    assert s.get("volume_weighted_note")
    assert s["strong_count"] >= 1


def test_report_meta_attach_after_close_shape():
    ar = {
        "date": "20260101",
        "overall_trend": "强势",
        "rising_ratio": 0.55,
        "trend_strength": 0.8,
    }
    ta._attach_report_meta("after_close", ar)
    rm = ar["report_meta"]
    assert rm["analysis_type"] == "after_close"
    assert "timestamp" in rm
    assert -1 <= rm["market_sentiment_score"] <= 1
    assert rm["trend_strength_label"] in ("strong", "neutral", "weak")
    assert isinstance(rm["key_metrics"], dict)
    assert rm["overlay"] == {}


def test_data_storage_opening_subdir_resolution():
    from src.data_storage import _trend_analysis_subdir_for_type

    trend_cfg = {
        "after_close_dir": "data/trend_analysis/after_close",
        "before_open_dir": "data/trend_analysis/before_open",
        "opening_dir": "data/trend_analysis/opening",
    }
    config = {"trend_analysis_plugin": {}}
    assert (
        _trend_analysis_subdir_for_type("opening_market", trend_cfg, config)
        == "data/trend_analysis/opening"
    )
    assert (
        _trend_analysis_subdir_for_type("before_open", trend_cfg, config)
        == "data/trend_analysis/before_open"
    )
    # 无 opening_dir 时回退默认
    trend_cfg2 = {k: v for k, v in trend_cfg.items() if k != "opening_dir"}
    sub = _trend_analysis_subdir_for_type("opening_market", trend_cfg2, config)
    assert "opening" in sub
