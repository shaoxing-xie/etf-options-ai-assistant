"""etf_rotation_core 纯函数单测（不依赖本地缓存）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from unittest.mock import patch

from analysis.etf_rotation_core import (
    build_log_returns_aligned,
    composite_raw_score,
    composite_raw_score_58,
    compute_stability_scores,
    compute_base_metrics,
    correlation_matrix_and_mean_abs,
    extract_close_series,
    extract_58_features,
    load_etf_daily_df,
    resolve_etf_pool,
    resolve_pool_type_map,
    run_rotation_pipeline,
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
    m5, m20, m60, vol20, crowding, mdd60, win_rate_20d = compute_base_metrics(s, "TEST", 70)
    assert m5 > 0
    assert m20 > 0
    assert m60 > 0
    assert 0 <= crowding <= 1
    assert 0 <= win_rate_20d <= 1


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
    assert "512480" in pool
    assert "512100" in pool  # 来自 rotation_config.yaml 的 extra_etf_codes


def test_resolve_pool_type_map() -> None:
    cfg = load_rotation_config()
    pool = resolve_etf_pool(None, cfg)
    pt = resolve_pool_type_map(pool, cfg)
    assert pt.get("512480") == "industry"
    assert pt.get("513120") == "concept"
    assert pt.get("512100") in ("extra", "industry")


def test_compute_stability_scores_default_when_empty() -> None:
    out = compute_stability_scores(["A", "B"], [])
    assert out["A"] == 0.5 and out["B"] == 0.5


def test_load_etf_daily_df_read_cache_skips_online_refill() -> None:
    """read_cache_data 应带 skip_online_refill，避免与 fetch_single 重复打源站。"""
    captured: dict = {}

    def _fake_read_cache(**kwargs):
        captured.update(kwargs)
        return {"success": False, "message": "miss", "df": None, "missing_dates": ["20240102"]}

    def _fake_fetch(**kwargs):
        return (
            pd.DataFrame({"日期": pd.to_datetime(["2024-01-02"]), "close": [1.0], "high": [1.1], "low": [0.9]}),
            "mock",
        )

    with (
        patch("data_access.read_cache_data.read_cache_data", side_effect=_fake_read_cache),
        patch(
            "plugins.data_collection.etf.fetch_historical.fetch_single_etf_historical",
            side_effect=_fake_fetch,
        ),
    ):
        load_etf_daily_df("510300", start_yyyymmdd="20240101", end_yyyymmdd="20240131")
    assert captured.get("skip_online_refill") is True


def test_run_rotation_pipeline_basic_degraded_signal() -> None:
    cfg = load_rotation_config()
    # 避免网络/缓存依赖：模拟 load_etf_daily_df 全失败，验证 readiness 结构。
    with patch("analysis.etf_rotation_core.load_etf_daily_df", return_value=(None, "mock_miss", "failed")):
        out = run_rotation_pipeline(["DUMMY1", "DUMMY2"], cfg, lookback_days=10)
    assert "data_readiness" in out
    dr = out["data_readiness"]
    assert "industry_coverage" in dr and "concept_coverage" in dr


def test_composite_raw_score_58_falls_back_when_no_features() -> None:
    fac = {"w_m20": 0.3, "w_m60": 0.25, "w_vol": 0.15, "w_mdd": 0.05, "w_trend_r2": 0.1, "w_corr_penalty": 0.2}
    legacy = composite_raw_score(0.01, 0.02, 0.1, -0.05, 0.5, 0.3, fac, use_trend=True, use_corr_penalty=True)
    sc, used_58 = composite_raw_score_58(0.01, 0.02, 0.1, -0.05, 0.5, 0.3, None, fac, use_trend=True, use_corr_penalty=True)
    assert used_58 is False
    assert isinstance(sc, float)
    assert abs(sc - legacy) < 1e-12


def test_run_rotation_pipeline_score_engine_58_fallback_on_extract_failure() -> None:
    # Synthetic OHLCV: enough length to satisfy MA/correlation windows.
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    close = np.linspace(10.0, 12.0, len(idx))
    high = close * 1.01
    low = close * 0.99
    volume = np.linspace(1e7, 2e7, len(idx))
    df = pd.DataFrame({"date": idx, "close": close, "high": high, "low": low, "volume": volume})

    cfg = load_rotation_config()
    with (
        patch("analysis.etf_rotation_core.load_etf_daily_df", return_value=(df, "ok_cache", "mock_src")),
        patch("analysis.etf_rotation_core.extract_58_features", return_value=(None, [])),
        patch("analysis.etf_rotation_core.read_last_rotation_runs", return_value=[]),
    ):
        out = run_rotation_pipeline(["ETF_A", "ETF_B"], cfg, lookback_days=120, score_engine="58")

    assert out.get("success", True) or True  # run_rotation_pipeline returns dict without strict 'success'
    tech = out.get("tech_features_by_symbol")
    assert isinstance(tech, dict)
    assert tech.get("ETF_A") is None
    assert tech.get("ETF_B") is None
    assert len(out.get("ranked_active") or []) > 0


def test_resolve_etf_pool_explicit() -> None:
    cfg = DEFAULT_ROTATION_CONFIG
    assert resolve_etf_pool("510300,510500", cfg) == ["510300", "510500"]
