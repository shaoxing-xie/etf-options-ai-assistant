"""signal_generation 配置归一化单测。"""

from src.signal_config_normalize import deep_merge_signal_dict, normalize_signal_generation_config


def test_deep_merge_nested_overlay_wins():
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    over = {"nested": {"y": 99}, "b": 2}
    out = deep_merge_signal_dict(base, over)
    assert out["a"] == 1
    assert out["b"] == 2
    assert out["nested"]["x"] == 1
    assert out["nested"]["y"] == 99


def test_normalize_no_signal_generation_only_warn_index():
    cfg = {
        "option_contracts": {
            "underlyings": [{"underlying": "510500", "call_contracts": [], "put_contracts": []}]
        }
    }
    normalize_signal_generation_config(cfg)
    assert cfg["option_contracts"]["underlyings"][0]["index_symbol"] == "000300"


def test_normalize_option_contracts_and_engine_and_intraday():
    cfg = {
        "option_contracts": {"current_month": "old", "underlyings": []},
        "signal_params": {"rsi_oversold": 40, "signal_strength_levels": {"weak": 0.45}},
        "signal_generation": {
            "option_contracts": {"current_month": "new"},
            "option": {
                "engine": {
                    "rsi_oversold": 38,
                    "signal_strength_levels": {"strong": 0.8},
                }
            },
            "intraday": {
                "by_underlying": {
                    "510300": {"enabled": True, "symbol": "510300"},
                }
            },
        },
    }
    normalize_signal_generation_config(cfg)
    assert cfg["option_contracts"]["current_month"] == "new"
    assert cfg["signal_params"]["rsi_oversold"] == 38
    assert cfg["signal_params"]["signal_strength_levels"]["weak"] == 0.45
    assert cfg["signal_params"]["signal_strength_levels"]["strong"] == 0.8
    assert cfg["signal_params"]["intraday_monitor_510300"]["enabled"] is True


def test_normalize_etf_short_term_merge():
    cfg = {
        "etf_trading": {"short_term": {"ma_long": 20, "enabled": True}},
        "signal_generation": {"etf": {"short_term": {"ma_long": 25}}},
    }
    normalize_signal_generation_config(cfg)
    assert cfg["etf_trading"]["short_term"]["ma_long"] == 25
    assert cfg["etf_trading"]["short_term"]["enabled"] is True


def test_normalize_stock_short_term():
    cfg = {
        "signal_params": {},
        "signal_generation": {"stock": {"short_term": {"volume_vs_ma5_mult": 1.5}}},
    }
    normalize_signal_generation_config(cfg)
    assert cfg["signal_params"]["stock_short_term"]["volume_vs_ma5_mult"] == 1.5


def test_normalize_option_contracts_underlyings_list_whole_replace():
    """signal_generation.option_contracts.underlyings replaces root list (not merged per row)."""
    cfg = {
        "option_contracts": {
            "underlyings": [{"underlying": "510300", "call_contracts": [], "put_contracts": []}],
        },
        "signal_generation": {
            "option_contracts": {
                "underlyings": [{"underlying": "510500", "call_contracts": [], "put_contracts": []}],
            },
        },
    }
    normalize_signal_generation_config(cfg)
    ul = cfg["option_contracts"]["underlyings"]
    assert len(ul) == 1
    assert ul[0]["underlying"] == "510500"
