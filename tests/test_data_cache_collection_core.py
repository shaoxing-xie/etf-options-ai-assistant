"""data_cache 采集核心：mock 数据源，无网络。"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sample_universe() -> dict:
    return {"index_codes": ["000300"], "etf_codes": ["510300"], "stock_codes": ["600519"]}


def _mock_fetch_ok(*_a, **_k):
    return {"success": True, "message": "ok"}


@patch("plugins.data_collection.stock.fetch_historical.tool_fetch_stock_historical", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.etf.fetch_historical.tool_fetch_etf_historical", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.index.fetch_historical.tool_fetch_index_historical", side_effect=_mock_fetch_ok)
@patch("src.data_cache_universe.get_data_cache_universe")
@patch("src.config_loader.load_system_config")
def test_morning_daily_steps_order(
    mock_cfg, mock_u, _ih, _eh, _sh, sample_universe
) -> None:
    mock_cfg.return_value = {}
    mock_u.return_value = sample_universe

    from src.data_cache_collection_core import run_data_cache_collection, summary_success

    summary = run_data_cache_collection("morning_daily")
    assert summary_success(summary)
    tools = [s.get("tool") for s in summary["steps"]]
    assert tools == ["index_historical", "etf_historical", "stock_historical"]


@patch("plugins.data_collection.stock.fetch_minute.tool_fetch_stock_minute", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.etf.fetch_minute.tool_fetch_etf_minute", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.index.fetch_minute.tool_fetch_index_minute", side_effect=_mock_fetch_ok)
@patch("src.data_cache_universe.get_data_cache_universe")
@patch("src.config_loader.load_system_config")
def test_intraday_throttle_stock_skips_at_minute_6(
    mock_cfg, mock_u, _im, _em, _sm, sample_universe
) -> None:
    mock_cfg.return_value = {}
    mock_u.return_value = sample_universe

    import pytz

    from src.data_cache_collection_core import run_data_cache_collection

    tz = pytz.timezone("Asia/Shanghai")
    now = tz.localize(datetime(2026, 4, 15, 10, 6, 0))

    summary = run_data_cache_collection(
        "intraday_minute", throttle_stock=True, now=now
    )
    stock_steps = [s for s in summary["steps"] if s.get("tool") == "stock_minute"]
    assert len(stock_steps) == 1
    assert stock_steps[0].get("skipped") is True
    assert stock_steps[0].get("reason") == "throttle_stock"


@patch("plugins.data_collection.stock.fetch_minute.tool_fetch_stock_minute", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.etf.fetch_minute.tool_fetch_etf_minute", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.index.fetch_minute.tool_fetch_index_minute", side_effect=_mock_fetch_ok)
@patch("src.data_cache_universe.get_data_cache_universe")
@patch("src.config_loader.load_system_config")
def test_intraday_throttle_stock_runs_at_minute_1(
    mock_cfg, mock_u, _im, _em, _sm, sample_universe
) -> None:
    mock_cfg.return_value = {}
    mock_u.return_value = sample_universe

    import pytz

    from src.data_cache_collection_core import run_data_cache_collection, summary_success

    tz = pytz.timezone("Asia/Shanghai")
    now = tz.localize(datetime(2026, 4, 15, 10, 1, 0))

    summary = run_data_cache_collection(
        "intraday_minute", throttle_stock=True, now=now
    )
    assert summary_success(summary)
    stock_steps = [s for s in summary["steps"] if s.get("tool") == "stock_minute" and "skipped" not in s]
    assert len(stock_steps) == 1
    assert stock_steps[0].get("success") is True


@patch("plugins.data_collection.stock.fetch_historical.tool_fetch_stock_historical", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.etf.fetch_historical.tool_fetch_etf_historical", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.index.fetch_historical.tool_fetch_index_historical", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.stock.fetch_minute.tool_fetch_stock_minute", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.etf.fetch_minute.tool_fetch_etf_minute", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.index.fetch_minute.tool_fetch_index_minute", side_effect=_mock_fetch_ok)
@patch("src.data_cache_universe.get_data_cache_universe")
@patch("src.config_loader.load_system_config")
def test_close_minute_has_daily_refresh_step(
    mock_cfg, mock_u, _im, _em, _sm, _ih, _eh, _sh, sample_universe
) -> None:
    mock_cfg.return_value = {}
    mock_u.return_value = sample_universe

    from src.data_cache_collection_core import run_data_cache_collection, summary_success

    summary = run_data_cache_collection("close_minute")
    assert summary_success(summary)
    notes = [s for s in summary["steps"] if s.get("tool") == "daily_historical_after_close"]
    assert len(notes) == 1
    # after note: three historical steps
    assert any(s.get("tool") == "index_historical" for s in summary["steps"])


@patch("plugins.data_collection.stock.fetch_historical.tool_fetch_stock_historical", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.etf.fetch_historical.tool_fetch_etf_historical", side_effect=_mock_fetch_ok)
@patch("plugins.data_collection.index.fetch_historical.tool_fetch_index_historical", return_value={"success": False, "message": "fail"})
@patch("src.data_cache_universe.get_data_cache_universe")
@patch("src.config_loader.load_system_config")
def test_summary_success_false_when_step_fails(mock_cfg, mock_u, _ih, _eh, _sh, sample_universe) -> None:
    mock_cfg.return_value = {}
    mock_u.return_value = sample_universe

    from src.data_cache_collection_core import run_data_cache_collection, summary_success

    summary = run_data_cache_collection("morning_daily")
    assert not summary_success(summary)


def test_cli_main_return_code_matches_core(sample_universe) -> None:
    """scripts/run_data_cache_collection.py main() 与核心同一套 mock 下退出码为 0。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "rcc_cli", ROOT / "scripts" / "run_data_cache_collection.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with patch("src.config_loader.load_system_config", return_value={}):
        with patch("src.data_cache_universe.get_data_cache_universe", return_value=sample_universe):
            with patch(
                "plugins.data_collection.index.fetch_historical.tool_fetch_index_historical",
                side_effect=_mock_fetch_ok,
            ):
                with patch(
                    "plugins.data_collection.etf.fetch_historical.tool_fetch_etf_historical",
                    side_effect=_mock_fetch_ok,
                ):
                    with patch(
                        "plugins.data_collection.stock.fetch_historical.tool_fetch_stock_historical",
                        side_effect=_mock_fetch_ok,
                    ):
                        old = sys.argv
                        try:
                            sys.argv = ["run_data_cache_collection.py", "morning_daily"]
                            rc = mod.main()
                        finally:
                            sys.argv = old
                        assert rc == 0
