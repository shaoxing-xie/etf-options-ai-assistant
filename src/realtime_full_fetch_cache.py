"""
实时行情“全量拉取 + 再筛选” 的短缓存工具。

使用场景：
- ETF 实时 spot：ak.fund_etf_spot_ths(date="") 拉全量表后筛选目标代码
- 指数现货快照：ak.stock_zh_index_spot_sina()；东财 ak.stock_zh_index_spot_em(symbol=...) 按分类多次拉取（各分类独立缓存键）
- 其它类似“全量列表/全市场快照”场景

约束：
- 仅做进程内内存缓存（避免落地文件与跨进程一致性问题）
- 缓存 TTL 可由 config.yaml 统一配置
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Dict, Optional, Tuple
import time


@dataclass
class _CacheEntry:
    ts: float
    value: Any


_cache: Dict[str, _CacheEntry] = {}
_lock = Lock()

# 配置刷新周期：避免每次请求都重新读 config.yaml
_CFG_REFRESH_SECONDS = 60.0
_cfg_cache: Optional[Dict[str, Any]] = None
_cfg_ts: float = 0.0


def _load_cfg() -> Dict[str, Any]:
    global _cfg_cache, _cfg_ts
    now = time.time()
    if _cfg_cache is not None and (now - _cfg_ts) <= _CFG_REFRESH_SECONDS:
        return _cfg_cache

    try:
        from src.config_loader import load_system_config

        cfg = load_system_config(use_cache=True)
        rt_cfg = cfg.get("realtime_full_fetch_cache", {}) if isinstance(cfg, dict) else {}
        if not isinstance(rt_cfg, dict):
            rt_cfg = {}
        _cfg_cache = rt_cfg
        _cfg_ts = now
        return rt_cfg
    except Exception:
        # 保守：默认开启，TTL=45 秒
        _cfg_cache = {"enabled": True, "ttl_seconds": 45}
        _cfg_ts = now
        return _cfg_cache


def _is_enabled_and_ttl(ttl_seconds: Optional[float] = None) -> Tuple[bool, float]:
    cfg = _load_cfg()
    enabled = bool(cfg.get("enabled", True))
    ttl = float(cfg.get("ttl_seconds", 45))
    if ttl_seconds is not None:
        ttl = float(ttl_seconds)
    ttl = max(0.0, ttl)
    return enabled, ttl


def get_or_fetch(
    cache_key: str,
    fetch_fn: Callable[[], Any],
    *,
    ttl_seconds: Optional[float] = None,
) -> Any:
    """
    命中缓存就返回缓存值，否则调用 fetch_fn 并写入缓存。
    """
    enabled, ttl = _is_enabled_and_ttl(ttl_seconds=ttl_seconds)
    if not enabled or ttl <= 0:
        return fetch_fn()

    now = time.time()
    with _lock:
        entry = _cache.get(cache_key)
        if entry is not None and (now - entry.ts) <= ttl:
            return entry.value

    # 缓存未命中：先不持锁执行 fetch_fn（避免 fetch_fn 慢导致阻塞）
    value = fetch_fn()

    with _lock:
        _cache[cache_key] = _CacheEntry(ts=now, value=value)
    return value


def clear_cache(cache_key_prefix: Optional[str] = None) -> None:
    with _lock:
        if cache_key_prefix is None:
            _cache.clear()
            return
        for k in list(_cache.keys()):
            if k.startswith(cache_key_prefix):
                _cache.pop(k, None)

