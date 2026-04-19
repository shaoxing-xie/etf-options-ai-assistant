"""
从 load_system_config() 合并后的 data_cache 节读取「采集缓存标的」清单。

与 Cron 任务、scripts/run_data_cache_collection.py 共用，避免与 symbols.json 双轨漂移时无据可查。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _dedupe_str_list(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for x in raw:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _merge_rotation_etf_codes_into(base: List[str]) -> List[str]:
    """
    将 `rotation_config.yaml` + `symbols.json` 解析出的轮动池 ETF 并入采集清单，
    使 morning_daily / close_minute 的长窗日 K 覆盖轮动读盘路径，减少冷补采。
    """
    try:
        from analysis.etf_rotation_core import resolve_etf_pool
        from src.rotation_config_loader import load_rotation_config

        rcfg = load_rotation_config(None)
        rot = resolve_etf_pool(None, rcfg)
    except Exception:
        return base
    if not rot:
        return base
    seen = set(base)
    out = list(base)
    for s in rot:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def get_data_cache_universe(config: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
    """
    Returns:
        {"index_codes": [...], "etf_codes": [...], "stock_codes": [...]}
    """
    if config is None:
        from src.config_loader import load_system_config

        config = load_system_config(use_cache=True)

    dc = config.get("data_cache") or {}
    if not isinstance(dc, dict):
        dc = {}

    etf_codes = _dedupe_str_list(dc.get("etf_codes"))
    etf_codes = _merge_rotation_etf_codes_into(etf_codes)

    return {
        "index_codes": _dedupe_str_list(dc.get("index_codes")),
        "etf_codes": etf_codes,
        "stock_codes": _dedupe_str_list(dc.get("stock_codes")),
    }
