from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src import stock_code_map_cache as scm


def test_normalize_and_load(tmp_path: Path) -> None:
    p = tmp_path / "m.json"
    p.write_text('{"1": "甲", "000002": "万科A"}\n', encoding="utf-8")
    m = scm.load_code_str_map(p)
    assert m.get("000001") == "甲"
    assert m.get("000002") == "万科A"


def test_resolve_names_order(tmp_path: Path) -> None:
    root = tmp_path
    scm.path_local_stock_name(root).parent.mkdir(parents=True, exist_ok=True)
    scm.path_local_stock_name(root).write_text(json.dumps({"000001": "本地名"}, ensure_ascii=False), encoding="utf-8")
    scm.path_cache_stock_name(root).parent.mkdir(parents=True, exist_ok=True)
    scm.path_cache_stock_name(root).write_text(json.dumps({"000001": "缓存名", "000002": "缓存二"}, ensure_ascii=False), encoding="utf-8")

    def fetch(missing: list[str]) -> dict[str, str]:
        assert sorted(missing) == ["600000"]
        return {"600000": "浦发"}

    got = scm.resolve_stock_names_cached(["000001", "000002", "600000"], root=root, fetch_missing=fetch)
    assert got["000001"] == "本地名"
    assert got["000002"] == "缓存二"
    assert got["600000"] == "浦发"


def test_resolve_names_skips_fetch_when_complete(tmp_path: Path) -> None:
    root = tmp_path
    scm.path_local_stock_name(root).parent.mkdir(parents=True, exist_ok=True)
    scm.path_local_stock_name(root).write_text(json.dumps({"000001": "x"}, ensure_ascii=False), encoding="utf-8")

    def fetch(_: list[str]) -> dict[str, str]:
        raise AssertionError("should not fetch")

    got = scm.resolve_stock_names_cached(["000001"], root=root, fetch_missing=fetch)
    assert got == {"000001": "x"}


def test_write_back_sector_respects_local(tmp_path: Path) -> None:
    root = tmp_path
    scm.path_local_stock_sector(root).parent.mkdir(parents=True, exist_ok=True)
    scm.path_local_stock_sector(root).write_text(json.dumps({"000001": "手工板块"}, ensure_ascii=False), encoding="utf-8")
    merged = {"000001": "银行", "600000": "银行"}
    scm.write_back_sector_cache(root, merged, ["000001", "600000"])
    cache = scm.load_code_str_map(scm.path_cache_stock_sector(root))
    assert "000001" not in cache
    assert cache.get("600000") == "银行"


@pytest.mark.parametrize("env_val,expect_write", [("0", False), ("1", True)])
def test_stock_map_cache_write_env(tmp_path: Path, env_val: str, expect_write: bool) -> None:
    root = tmp_path
    p = scm.path_cache_stock_name(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with patch.dict("os.environ", {"STOCK_MAP_CACHE_WRITE": env_val}, clear=False):
        scm.merge_write_code_str_map(p, {"000001": "A"})
    assert p.is_file() == expect_write
