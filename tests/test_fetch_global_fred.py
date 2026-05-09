"""FRED 日频兜底与解析单测（mock HTTP，无网络）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from plugins.data_collection.index.fetch_global import (
    YF_TO_FRED_SERIES,
    _fetch_fred_graph_rows,
    _parse_fred_graph_csv,
)


def test_parse_fred_graph_csv_skips_header_and_comments() -> None:
    text = "# note\nDATE,VALUE\n2026-05-01,16.5\n2026-05-02,17.25\n"
    rows = _parse_fred_graph_csv(text)
    assert rows == [("2026-05-01", 16.5), ("2026-05-02", 17.25)]


def test_yf_to_fred_series_covers_us_benchmarks() -> None:
    assert YF_TO_FRED_SERIES["^VIX"] == "VIXCLS"
    assert YF_TO_FRED_SERIES["^DJI"] == "DJIA"


@patch("requests.get")
def test_fetch_fred_graph_rows_vix(mock_get: MagicMock) -> None:
    rsp = MagicMock()
    rsp.status_code = 200
    rsp.text = "DATE,VALUE\n2026-05-06,17.39\n2026-05-07,18.10\n"
    rsp.raise_for_status = MagicMock()
    mock_get.return_value = rsp
    latest_cfg = {"throttle": {}}
    out = _fetch_fred_graph_rows(["^VIX"], latest_cfg, {})
    assert out.get("success") is True
    rows = out.get("data") or []
    assert len(rows) == 1
    r0 = rows[0]
    assert r0.get("code") == "^VIX"
    assert abs(float(r0.get("price") or 0) - 18.10) < 1e-6
    assert r0.get("source_id") == "fred"
    assert r0.get("data_semantics") == "fred_graph_eod"
