# -*- coding: utf-8 -*-
"""
股票 6 位代码 ↔ 简称、代码 ↔ 行业（板块）的本地映射缓存。

目录约定（均在仓库根下，相对 ROOT）：
- data/meta/local/stock_code_name.json    手工维护，优先级最高
- data/meta/local/stock_code_sector.json  手工维护，优先级最高
- data/meta/cache/stock_code_name.json    接口回填，次于 local
- data/meta/cache/stock_code_sector.json  接口回填，次于 local；次于 Tushare 全表文件

其他脚本：from src.stock_code_map_cache import ... 使用相同路径与读合并逻辑。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def path_local_stock_name(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "meta" / "local" / "stock_code_name.json"


def path_cache_stock_name(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "meta" / "cache" / "stock_code_name.json"


def path_local_stock_sector(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "meta" / "local" / "stock_code_sector.json"


def path_cache_stock_sector(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "meta" / "cache" / "stock_code_sector.json"


def looks_like_a_share_code(value: object) -> bool:
    s = str(value or "").strip().zfill(6)
    return len(s) == 6 and s.isdigit()


def normalize_code(value: object) -> str | None:
    s = str(value or "").strip().zfill(6)
    return s if len(s) == 6 and s.isdigit() else None


def load_code_str_map(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        nk = normalize_code(k)
        if nk is None:
            continue
        vs = str(v).strip()
        if not vs or vs.lower() in ("nan", "none"):
            continue
        out[nk] = vs
    return out


def _cache_write_enabled() -> bool:
    return (os.environ.get("STOCK_MAP_CACHE_WRITE") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def merge_write_code_str_map(path: Path, updates: dict[str, str]) -> None:
    """将 updates 合并写入 path（按键排序）；空 updates 不写盘。"""
    if not updates or not _cache_write_enabled():
        return
    cur = load_code_str_map(path)
    for k, v in updates.items():
        nk = normalize_code(k)
        if nk is None:
            continue
        vs = str(v).strip()
        if not vs or vs.lower() in ("nan", "none"):
            continue
        cur[nk] = vs
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({k: cur[k] for k in sorted(cur.keys())}, ensure_ascii=False, indent=2) + "\n"
    path.write_text(body, encoding="utf-8")


def resolve_stock_names_cached(
    codes: list[str],
    *,
    root: Path,
    fetch_missing: Callable[[list[str]], dict[str, str]],
) -> dict[str, str]:
    """
    名称解析顺序：local → cache → fetch_missing(codes)。
    fetch_missing 仅收到仍缺名称的 6 位代码列表；成功后把新结果合并写入 cache（不覆盖 local 中已有键的语义：
    写入时仍写入 fetch 结果到 cache，读取时 local 优先）。
    """
    uniq = sorted({c for c in (normalize_code(x) for x in codes) if c})
    if not uniq:
        return {}
    out: dict[str, str] = {}
    local = load_code_str_map(path_local_stock_name(root))
    cache = load_code_str_map(path_cache_stock_name(root))
    for c in uniq:
        if local.get(c):
            out[c] = local[c]
    for c in uniq:
        if c in out:
            continue
        if cache.get(c):
            out[c] = cache[c]
    missing = [c for c in uniq if not out.get(c)]
    fetched: dict[str, str] = {}
    if missing:
        fetched = fetch_missing(missing) or {}
        for k, v in fetched.items():
            nk = normalize_code(k)
            if nk is None:
                continue
            vs = str(v).strip()
            if vs and not looks_like_a_share_code(vs) and not out.get(nk):
                out[nk] = vs
    merge_write_code_str_map(path_cache_stock_name(root), fetched)
    return out


def load_sector_static_layers(root: Path, codes: list[str]) -> dict[str, str]:
    """local + cache/stock_code_sector，无网络。"""
    uniq = sorted({c for c in (normalize_code(x) for x in codes) if c})
    if not uniq:
        return {}
    local = load_code_str_map(path_local_stock_sector(root))
    cache = load_code_str_map(path_cache_stock_sector(root))
    merged: dict[str, str] = {}
    for c in uniq:
        if local.get(c):
            merged[c] = local[c]
    for c in uniq:
        if c in merged:
            continue
        if cache.get(c):
            merged[c] = cache[c]
    return merged


def local_sector_keys(root: Path) -> set[str]:
    """用于写回 cache 时跳过「手工表已声明」的代码（避免用接口结果覆盖手工意图）。"""
    return set(load_code_str_map(path_local_stock_sector(root)).keys())


def write_back_sector_cache(root: Path, merged: dict[str, str], codes: list[str]) -> None:
    """将本次解析到的行业写入 cache（不写入在 local 中有条目的代码）。"""
    uniq = {c for c in (normalize_code(x) for x in codes) if c}
    if not uniq:
        return
    skip = local_sector_keys(root)
    updates = {c: merged[c] for c in uniq if c in merged and merged.get(c) and c not in skip}
    merge_write_code_str_map(path_cache_stock_sector(root), updates)
