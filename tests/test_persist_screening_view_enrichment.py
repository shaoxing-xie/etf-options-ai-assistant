from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "persist_screening_view_snapshot",
    ROOT / "scripts" / "persist_screening_view_snapshot.py",
)
assert _spec and _spec.loader
_ps = importlib.util.module_from_spec(_spec)
sys.modules["persist_screening_view_snapshot_t"] = _ps
_spec.loader.exec_module(_ps)


def test_sector_from_row_prefers_industry() -> None:
    row = {"stock_code": "600000", "name": "浦发银行", "industry": "银行"}
    assert _ps._sector_from_row(row) == "银行"


def test_sector_from_row_empty_when_only_code_like() -> None:
    row = {"stock_code": "600000", "行业": "600000"}
    assert _ps._sector_from_row(row) == ""


def test_apply_sector_enrichment_fills_blank() -> None:
    payload = {
        "candidates": {
            "nightly": [],
            "tail": [{"symbol": "000001", "name": "平安银行", "sector_name": ""}],
        },
        "tail_paradigm_pools": {},
    }
    with patch.object(_ps, "_fetch_sector_map_merged", lambda syms: {"000001": "银行"}):
        _ps._apply_sector_enrichment(payload)
    assert payload["candidates"]["tail"][0]["sector_name"] == "银行"


def test_fetch_sector_map_merged_prefers_tushare_over_realtime() -> None:
    with patch.object(_ps, "write_back_sector_cache", lambda *a, **k: None):
        with patch.object(_ps, "load_sector_static_layers", return_value={}):
            with patch.object(_ps, "_load_tushare_industry_map_full", return_value={"000001": "银行"}):
                with patch.object(_ps, "_fetch_sector_map", return_value={"000001": "东财实时"}):
                    with patch.object(_ps, "_fetch_sector_map_akshare", return_value={}):
                        got = _ps._fetch_sector_map_merged(["000001"])
    assert got.get("000001") == "银行"


def test_fetch_sector_map_merged_falls_back_realtime_when_tushare_empty() -> None:
    with patch.object(_ps, "write_back_sector_cache", lambda *a, **k: None):
        with patch.object(_ps, "_load_tushare_industry_map_full", return_value={}):
            with patch.object(_ps, "_fetch_sector_map", return_value={"000001": "通信设备"}):
                with patch.object(_ps, "_fetch_sector_map_akshare", return_value={}):
                    got = _ps._fetch_sector_map_merged(["000001"])
    assert got.get("000001") == "通信设备"


def test_fetch_sector_map_merged_prefers_local_static_over_tushare() -> None:
    with patch.object(_ps, "write_back_sector_cache", lambda *a, **k: None):
        with patch.object(_ps, "load_sector_static_layers", return_value={"000001": "手工"}):
            with patch.object(_ps, "_load_tushare_industry_map_full", return_value={"000001": "银行"}):
                with patch.object(_ps, "_fetch_sector_map", return_value={}):
                    with patch.object(_ps, "_fetch_sector_map_akshare", return_value={}):
                        got = _ps._fetch_sector_map_merged(["000001"])
    assert got.get("000001") == "手工"
