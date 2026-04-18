"""global_hist_sina：mock 测试（不访问外网）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from plugins.data_collection.index.fetch_global_hist_sina import (
    _normalize_symbol,
    fetch_global_index_hist_sina,
)


@patch("plugins.data_collection.index.fetch_global_hist_sina._load_global_name_table")
@patch("plugins.data_collection.index.fetch_global_hist_sina.ak.index_global_hist_sina")
def test_fetch_global_hist_accepts_code_and_returns_tail(
    mock_hist: MagicMock, mock_tbl: MagicMock
) -> None:
    mock_tbl.return_value = ({"英国富时100指数": "UKX"}, {"UKX": "英国富时100指数"})
    mock_hist.return_value = pd.DataFrame(
        [
            {"date": "2026-04-08", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 0},
            {"date": "2026-04-09", "open": 2, "high": 3, "low": 1.5, "close": 2.5, "volume": 0},
            {"date": "2026-04-10", "open": 3, "high": 4, "low": 2.5, "close": 3.5, "volume": 0},
        ]
    )
    r = fetch_global_index_hist_sina("UKX", limit=2)
    assert r.get("success") is True
    assert r.get("count") == 2
    rows = r.get("data") or []
    assert rows[0]["date"] == "2026-04-09"
    assert rows[1]["date"] == "2026-04-10"
    assert "akshare.index_global_hist_sina" in str(r.get("source") or "")


@patch("plugins.data_collection.index.fetch_global_hist_sina._load_global_name_table")
def test_fetch_global_hist_rejects_unknown_symbol(mock_tbl: MagicMock) -> None:
    mock_tbl.return_value = ({"英国富时100指数": "UKX"}, {"UKX": "英国富时100指数"})
    try:
        fetch_global_index_hist_sina("NOT_EXIST", limit=10)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_normalize_accepts_opening_runner_yfinance_codes() -> None:
    """开盘补采欧股/韩股时传入 ^FTSE 等，须能归一化到新浪 hist 内部码。"""
    assert _normalize_symbol("^FTSE") == "UKX"
    assert _normalize_symbol("^GDAXI") == "DAX"
    assert _normalize_symbol("^STOXX50E") == "SX5E"
    assert _normalize_symbol("^KS11") == "KOSPI"
    assert _normalize_symbol("^GSPC") == "SPX"

