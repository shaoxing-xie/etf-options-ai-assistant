"""
加载 config/rotation_config.yaml，供 ETF 轮动研究与回测共用。
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)

DEFAULT_ROTATION_CONFIG: Dict[str, Any] = {
    "version": 1,
    "pool": {"symbol_groups": ["core", "industry_etf"], "extra_etf_codes": ["512100", "512880", "512690"]},
    "features": {
        "use_correlation": True,
        "use_ma": True,
        "use_trend_r2": True,
        "use_vol_gate": False,
        "use_mdd_gate": False,
    },
    "factors": {
        "w_m20": 0.30,
        "w_m60": 0.25,
        "w_vol": 0.15,
        "w_mdd": 0.05,
        "w_trend_r2": 0.10,
        "w_corr_penalty": 0.20,
    },
    "legacy_factors": {"w_m20": 0.45, "w_m60": 0.35, "w_vol": 0.15, "w_mdd": 0.05},
    "filters": {
        "min_history_days": 70,
        "correlation_lookback": 252,
        "correlation_mode": "penalize",
        "correlation_threshold": 0.70,
        "correlation_pairwise_max": 0.85,
        "ma_period": 200,
        "ma_mode": "soft",
        "ma_below_penalty": 0.5,
        "trend_r2_window": 60,
        "vol_min": 0.0,
        "vol_max": 1.0,
        "vol_gate_mode": "off",
        "vol_soft_penalty": 0.5,
        "mdd60_threshold": -0.99,
        "mdd_gate_mode": "off",
        "mdd_soft_penalty": 0.7,
    },
    "paths": {"history_jsonl": "data/etf_rotation_runs.jsonl"},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[assignment]
        else:
            out[k] = v
    return out


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_rotation_config_path() -> Path:
    return _project_root() / "config" / "rotation_config.yaml"


def load_rotation_config(path: Optional[str] = None) -> Dict[str, Any]:
    """
    加载 rotation 配置；文件缺失或解析失败时返回内置默认并打日志。
    """
    cfg_path = Path(path) if path else default_rotation_config_path()
    if yaml is None:
        logger.warning("rotation_config_loader: PyYAML 不可用，使用内置默认")
        return deepcopy(DEFAULT_ROTATION_CONFIG)
    if not cfg_path.exists():
        logger.warning("rotation_config_loader: 配置文件不存在: %s，使用内置默认", cfg_path)
        return deepcopy(DEFAULT_ROTATION_CONFIG)
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            return deepcopy(DEFAULT_ROTATION_CONFIG)
        return _deep_merge(DEFAULT_ROTATION_CONFIG, raw)
    except Exception as e:
        logger.error("rotation_config_loader: 读取失败: %s, error=%s", cfg_path, e)
        return deepcopy(DEFAULT_ROTATION_CONFIG)


__all__ = ["load_rotation_config", "default_rotation_config_path", "DEFAULT_ROTATION_CONFIG"]
