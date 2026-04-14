"""etf_rotation_core 纯函数单测（不依赖本地缓存）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.etf_rotation_core import (
    build_log_returns_aligned,
    composite_raw_score,
    compute_base_metrics,
    correlation_matrix_and_mean_abs,
    extract_close_series,
    resolve_etf_pool,
    trim_dataframe,
)
from src.rotation_config_loader import DEFAULT_ROTATION_CONFIG, load_rotation_config


def test_trim_dataframe() -> None:
    df = pd.DataFrame({"close": range(500), "date": pd.date_range("2020-01-01", periods=500)})
    out = trim_dataframe(df, lookback_days=100, data_need=300)
    assert len(out) == 300


def test_extract_close_series_with_date() -> None:
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=100),
            "close": np.linspace(1.0, 2.0, 100),
        }
    )
    s, _ = extract_close_series(df)
    assert len(s) == 100
    assert len(s) == len(s.index.unique())


def test_compute_base_metrics() -> None:
    x = np.linspace(1.0, 1.5, 100)
    s = pd.Series(x)
    m20, m60, vol20, mdd60 = compute_base_metrics(s, "TEST", 70)
    assert m20 > 0
    assert m60 > 0


def test_build_log_returns_aligned() -> None:
    idx = pd.date_range("2023-01-01", periods=300, freq="B")
    a = pd.Series(np.linspace(1.0, 1.2, len(idx)), index=idx)
    b = pd.Series(np.linspace(1.0, 1.15, len(idx)), index=idx)
    rets, w = build_log_returns_aligned({"a": a, "b": b}, 120)
    assert rets is not None
    assert rets.shape[1] == 2
    corr, mean_abs = correlation_matrix_and_mean_abs(rets)
    assert "a" in mean_abs and "b" in mean_abs


def test_composite_raw_score() -> None:
    fac = {"w_m20": 0.3, "w_m60": 0.25, "w_vol": 0.15, "w_mdd": 0.05, "w_trend_r2": 0.1, "w_corr_penalty": 0.2}
    sc = composite_raw_score(0.01, 0.02, 0.1, -0.05, 0.5, 0.3, fac, use_trend=True, use_corr_penalty=True)
    assert isinstance(sc, float)


def test_resolve_etf_pool_empty_uses_config() -> None:
    cfg = load_rotation_config()
    pool = resolve_etf_pool(None, cfg)
    assert len(pool) >= 4
    assert "510300" in pool


def test_resolve_etf_pool_explicit() -> None:
    cfg = DEFAULT_ROTATION_CONFIG
    assert resolve_etf_pool("510300,510500", cfg) == ["510300", "510500"]
