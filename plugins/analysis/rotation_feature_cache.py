"""
日终一行 58 特征磁盘缓存（rotation58_p0_v1）。

与 docs/research/etf_rotation_cache_benchmark_and_proposal.md §4 对齐：键含 symbol、feature_set、
macd_factor、rotation 配置指纹、最后一根 K 线日期。失效：任一不匹配则重算并覆盖。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

FEATURE_SET_ID = "rotation58_p0_v1"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def fingerprint_58_cache(config: Dict[str, Any], macd_factor: float) -> str:
    payload = {
        "feature_set": FEATURE_SET_ID,
        "rotation_version": config.get("version"),
        "macd_factor": round(float(macd_factor), 6),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:20]


def last_bar_yyyymmdd_from_df(df) -> Optional[str]:
    import pandas as pd  # local: tools discovery

    for c in ("日期", "date", "trade_date", "datetime", "时间"):
        if c in df.columns:
            dt = pd.to_datetime(df[c], errors="coerce").dropna()
            if len(dt):
                return str(dt.iloc[-1].strftime("%Y%m%d"))
    return None


def cache_enabled() -> bool:
    return os.environ.get("ROTATION_58_FEATURE_CACHE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _cache_file(symbol: str) -> Path:
    d = _project_root() / "data" / "rotation_feature_cache" / str(symbol)
    d.mkdir(parents=True, exist_ok=True)
    return d / "features_58_v1.json"


def try_load_58(
    symbol: str,
    last_bar_yyyymmdd: str,
    fp: str,
) -> Optional[Dict[str, float]]:
    if not cache_enabled():
        return None
    path = _cache_file(symbol)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if raw.get("feature_set") != FEATURE_SET_ID:
        return None
    if raw.get("last_bar") != str(last_bar_yyyymmdd) or raw.get("config_fp") != fp:
        return None
    feat = raw.get("features")
    if not isinstance(feat, dict):
        return None
    out: Dict[str, float] = {}
    for k, v in feat.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            return None
    return out


def save_58(symbol: str, last_bar_yyyymmdd: str, fp: str, features: Dict[str, float]) -> None:
    if not cache_enabled():
        return
    path = _cache_file(symbol)
    payload = {
        "feature_set": FEATURE_SET_ID,
        "last_bar": str(last_bar_yyyymmdd),
        "config_fp": fp,
        "features": {k: float(v) for k, v in features.items()},
    }
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        try:
            if tmp.is_file():
                tmp.unlink()
        except Exception:
            pass
