#!/usr/bin/env python3
"""
Unified configuration for backtesting-trading-strategies.

Loads ``config/settings.yaml`` under the skill root (parent of ``scripts/``).
Override path with env ``BACKTEST_SKILL_SETTINGS`` (absolute or ``~`` path).

Precedence for data provider (same family as ``--data-source`` / ``--source``):
  CLI > ``BACKTEST_DATA_SOURCE`` env > ``data.provider`` in YAML > ``auto``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional


def skill_root_from_script_file() -> Path:
    """Skill root: ``skills/backtesting-trading-strategies/``."""
    return Path(__file__).resolve().parent.parent


def settings_yaml_path(skill_root: Path) -> Path:
    override = os.environ.get("BACKTEST_SKILL_SETTINGS", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (skill_root / "config" / "settings.yaml").resolve()


def _default_settings() -> Dict[str, Any]:
    return {
        "data": {
            "provider": "auto",
            "cache_dir": "./data",
            "default_interval": "1d",
        },
        "backtest": {
            "default_capital": 10000.0,
            "commission": 0.001,
            "slippage": 0.0005,
        },
        "reporting": {
            "output_dir": "./reports",
            "save_trades": True,
            "save_equity": True,
            "save_chart": True,
        },
        "risk": {
            "max_position_size": 0.95,
            "stop_loss": None,
            "take_profit": None,
        },
        "strategies": {},
    }


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_skill_settings(skill_root: Path) -> Dict[str, Any]:
    path = settings_yaml_path(skill_root)
    defaults = _default_settings()
    if not path.is_file():
        return defaults
    try:
        import yaml

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            return defaults
        return _deep_merge(defaults, raw)
    except Exception:
        return defaults


def resolve_skill_path(skill_root: Path, path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p.resolve()
    return (skill_root / path_str).resolve()


def normalize_data_source(value: Optional[str]) -> str:
    """Return one of: auto, china, yfinance, coingecko."""
    if value is None:
        return "auto"
    v = str(value).strip().lower()
    if not v:
        return "auto"
    if v in ("plugin", "china_stock", "cn"):
        return "china"
    if v in ("auto", "china", "yfinance", "coingecko"):
        return v
    return "auto"


def effective_data_source(skill_root: Path, cli: Optional[str] = None) -> str:
    if cli is not None and str(cli).strip() != "":
        return normalize_data_source(cli)
    env = os.environ.get("BACKTEST_DATA_SOURCE", "").strip()
    if env:
        return normalize_data_source(env)
    settings = load_skill_settings(skill_root)
    prov = settings.get("data", {}).get("provider", "auto")
    return normalize_data_source(prov)
