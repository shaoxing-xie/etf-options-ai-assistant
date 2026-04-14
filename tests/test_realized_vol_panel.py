"""realized_vol_panel 与 calculate_historical_volatility 委托一致性。"""
import numpy as np
import pandas as pd
from src.indicator_calculator import calculate_historical_volatility
from src.realized_vol_panel import (
    merge_historical_snapshot_config,
    realized_vol_windows,
    volatility_cone_for_windows,
)


def _sample_price_df(n: int = 120, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    r = rng.normal(0.001, 0.02, size=n)
    px = 100 * np.cumprod(1 + r)
    return pd.DataFrame({"收盘": px})


def test_realized_vol_matches_calculate_historical_volatility():
    df = _sample_price_df(200)
    for period in (5, 20, 60):
        m = realized_vol_windows(df, [period], close_col="收盘", data_period="day")
        hv_panel = m.get(str(period))
        hv_legacy = calculate_historical_volatility(df, period=period, close_col="收盘", data_period="day")
        assert hv_panel is not None and hv_legacy is not None
        assert abs(hv_panel - hv_legacy) < 1e-9


def test_insufficient_window_returns_none():
    df = _sample_price_df(10)
    m = realized_vol_windows(df, [20], close_col="收盘")
    assert m.get("20") is None


def test_volatility_cone_has_percentile():
    df = _sample_price_df(300)
    cone = volatility_cone_for_windows(df, [20], close_col="收盘", min_history_points=30)
    assert "20" in cone
    c20 = cone["20"]
    assert "percentile" in c20
    assert "min" in c20 and "max" in c20 and "mean" in c20
    assert 0 <= c20["percentile"] <= 100


def test_merge_historical_snapshot_config_defaults():
    c = merge_historical_snapshot_config({})
    assert c["enabled"] is True
    assert 252 in c["default_windows"]
    assert c["iv"]["near_month_min_days"] == 7
