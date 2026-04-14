"""fetch_global：AkShare 美股日 K 兜底（mock，无网络）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from plugins.data_collection.index.fetch_global import fetch_global_index_spot


@patch("plugins.data_collection.index.fetch_global._fetch_akshare_us_index_sina_rows")
@patch("plugins.data_collection.index.fetch_global._eastmoney_global_spot_by_em_code", return_value={})
@patch("plugins.data_collection.index.fetch_global._fetch_sina")
@patch("plugins.data_collection.index.fetch_global._fetch_yfinance")
def test_akshare_fills_us_when_yf_partial_sina_empty(
    mock_yf: MagicMock, mock_sina: MagicMock, mock_em: MagicMock, mock_ak: MagicMock
) -> None:
    mock_yf.return_value = {
        "success": True,
        "data": [
            {
                "code": "^HSI",
                "name": "恒生指数",
                "price": 26000.0,
                "change": 1.0,
                "change_pct": 0.5,
                "timestamp": "t",
            }
        ],
    }
    mock_sina.return_value = {"success": False, "data": []}
    mock_ak.return_value = [
        {
            "code": "^DJI",
            "name": "道琼斯",
            "price": 40000.0,
            "change": 10.0,
            "change_pct": 0.03,
            "timestamp": "t2",
            "source_detail": "akshare.index_us_stock_sina(.DJI);bar_date=2026-04-10",
        }
    ]
    r = fetch_global_index_spot("^HSI,^DJI")
    assert r.get("success") is True
    by = {row["code"]: row for row in (r.get("data") or []) if isinstance(row, dict)}
    assert "^HSI" in by and "^DJI" in by
    src = str(r.get("source") or "")
    assert "akshare.index_us_stock_sina" in src


@patch("plugins.data_collection.index.fetch_global._fetch_akshare_us_index_sina_rows")
@patch("plugins.data_collection.index.fetch_global._eastmoney_global_spot_by_em_code", return_value={})
@patch("plugins.data_collection.index.fetch_global._fetch_sina")
@patch("plugins.data_collection.index.fetch_global._fetch_yfinance")
def test_akshare_fills_when_yf_and_sina_fail(
    mock_yf: MagicMock, mock_sina: MagicMock, mock_em: MagicMock, mock_ak: MagicMock
) -> None:
    mock_yf.return_value = {"success": False, "data": []}
    mock_sina.return_value = {"success": False, "data": []}
    mock_ak.return_value = [
        {
            "code": "^DJI",
            "name": "道琼斯",
            "price": 1.0,
            "change": 0.1,
            "change_pct": 10.0,
            "timestamp": "t",
            "source_detail": "akshare.index_us_stock_sina(.DJI);bar_date=x",
        }
    ]
    r = fetch_global_index_spot("^DJI")
    assert r.get("success") is True
    rows = r.get("data") or []
    assert len(rows) == 1 and rows[0].get("code") == "^DJI"
    src = str(r.get("source") or "")
    assert "akshare.index_us_stock_sina" in src
    assert "yfinance" in src


@patch("plugins.data_collection.index.fetch_global._fetch_akshare_us_index_sina_rows")
@patch("plugins.data_collection.index.fetch_global._fetch_sina")
@patch("plugins.data_collection.index.fetch_global._fetch_yfinance")
@patch("plugins.data_collection.index.fetch_global._tavily_global_digest_fallback", return_value=None)
def test_akshare_pure_source_second_pass_after_sina_full_fails(
    mock_tav: MagicMock,
    mock_yf: MagicMock,
    mock_sina: MagicMock,
    mock_ak: MagicMock,
) -> None:
    """yf 与整包新浪 hq 失败后，第二段仅 AkShare 成功时 source 为 akshare.index_us_stock_sina。"""
    mock_yf.return_value = {"success": False, "data": []}
    mock_sina.side_effect = [
        {"success": False, "data": []},
        {"success": False, "data": []},
    ]
    mock_ak.side_effect = [
        [],
        [
            {
                "code": "^DJI",
                "name": "道琼斯",
                "price": 2.0,
                "change": 0.2,
                "change_pct": 11.0,
                "timestamp": "t",
                "source_detail": "akshare.index_us_stock_sina(.DJI);bar_date=y",
            }
        ],
    ]
    r = fetch_global_index_spot("^DJI")
    assert r.get("success") is True
    assert r.get("source") == "akshare.index_us_stock_sina"
    assert (r.get("data") or [{}])[0].get("code") == "^DJI"
