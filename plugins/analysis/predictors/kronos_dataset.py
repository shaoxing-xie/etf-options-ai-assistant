from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from src.data_collector import fetch_index_daily_em


@dataclass(frozen=True)
class KronosDataset:
    feature_names: Tuple[str, ...]
    X: np.ndarray
    y: np.ndarray
    latest_features: Dict[str, float]
    sample_count: int


def _daily_df(symbol: str, *, lookback_days: int = 900) -> pd.DataFrame:
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=max(lookback_days * 2, 900))
    df = fetch_index_daily_em(
        symbol=symbol,
        start_date=start_dt.strftime("%Y%m%d"),
        end_date=end_dt.strftime("%Y%m%d"),
    )
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out.get("日期", out.get("date")), errors="coerce")
    out["close"] = pd.to_numeric(out.get("收盘", out.get("close")), errors="coerce")
    out["volume"] = pd.to_numeric(out.get("成交量", out.get("volume")), errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").tail(lookback_days).reset_index(drop=True)
    return out


def _build_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    frame = df[["date", "close", "volume"]].copy()
    frame["ret1"] = frame["close"].pct_change(1)
    frame["ret3"] = frame["close"].pct_change(3)
    frame["ret5"] = frame["close"].pct_change(5)
    frame["ret10"] = frame["close"].pct_change(10)
    frame["ret20"] = frame["close"].pct_change(20)
    frame["vol_ratio_1d_5d"] = frame["volume"] / frame["volume"].rolling(5).mean()
    frame["volatility_5d"] = frame["close"].pct_change().rolling(5).std()
    frame["volatility_20d"] = frame["close"].pct_change().rolling(20).std()
    frame["mom_gap_5_20"] = frame["ret5"] - frame["ret20"]
    frame["ret_accel"] = frame["ret5"] - frame["ret10"]
    frame["target"] = (frame["close"].shift(-1) > frame["close"]).astype(float)
    return frame


def build_kronos_dataset(symbol: str) -> KronosDataset:
    feature_names = (
        "ret1",
        "ret3",
        "ret5",
        "ret10",
        "ret20",
        "vol_ratio_1d_5d",
        "volatility_5d",
        "volatility_20d",
        "mom_gap_5_20",
        "ret_accel",
    )
    df = _daily_df(symbol)
    frame = _build_feature_frame(df)
    latest_row = frame.iloc[-1] if not frame.empty else {}
    latest_features = {
        name: float(latest_row[name]) if name in latest_row and pd.notna(latest_row[name]) else 0.0 for name in feature_names
    }
    clean = frame.dropna(subset=list(feature_names) + ["target"]).copy()
    if len(clean) < 80:
        return KronosDataset(feature_names=feature_names, X=np.zeros((0, len(feature_names))), y=np.zeros(0), latest_features=latest_features, sample_count=0)
    X = clean.loc[:, list(feature_names)].to_numpy(dtype=float)
    y = clean["target"].to_numpy(dtype=float)
    return KronosDataset(feature_names=feature_names, X=X, y=y, latest_features=latest_features, sample_count=len(clean))
