"""
data_collection 变更插件与工具的全面测试：
- 单元测试（mock，不依赖外网）
- CLI（tool_runner）冒烟：校验 JSON 结构与关键字段
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parents[1]


def _run_tool_cli(tool: str, args: dict) -> dict:
    runner = BASE_DIR / "tool_runner.py"
    proc = subprocess.run(
        [
            str(BASE_DIR / ".venv" / "bin" / "python"),
            str(runner),
            tool,
            json.dumps(args, ensure_ascii=False),
        ],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    out = proc.stdout.strip()
    assert out
    return json.loads(out)


# --- 配置与契约 ---


def test_load_symbol_mapping_yaml() -> None:
    from plugins.data_collection.config import load_symbol_mapping

    data = load_symbol_mapping()
    assert "mappings" in data
    assert isinstance(data["mappings"], list)
    assert any(m.get("etf") == "510300" for m in data["mappings"])


def test_tool_map_registers_data_collection_stock_and_etf_tools() -> None:
    from tool_runner import TOOL_MAP

    assert "tool_fetch_stock_realtime" in TOOL_MAP
    assert "tool_fetch_stock_historical" in TOOL_MAP
    assert "tool_fetch_stock_minute" in TOOL_MAP
    assert "tool_fetch_etf_iopv_snapshot" in TOOL_MAP
    assert TOOL_MAP["tool_fetch_stock_realtime"].module_path.startswith("plugins.data_collection")


# --- 股票实时链 ---


def test_run_stock_realtime_chain_single_code_tries_bid_before_tencent() -> None:
    with (
        patch(
            "plugins.data_collection.stock.fetch_realtime._fetch_realtime_mootdx",
            return_value=None,
        ),
        patch(
            "plugins.data_collection.stock.fetch_realtime._fetch_bid_ask_em_single",
            return_value=[
                {
                    "stock_code": "600000",
                    "current_price": 10.0,
                    "quote_type": "depth",
                }
            ],
        ),
        patch(
            "plugins.data_collection.stock.fetch_realtime._fetch_realtime_tencent",
        ) as mock_tx,
        patch(
            "plugins.data_collection.stock.fetch_realtime._fetch_realtime_akshare",
        ),
    ):
        from plugins.data_collection.stock.fetch_realtime import run_stock_realtime_chain

        rows, src, _ = run_stock_realtime_chain(["600000"], include_depth=True)
        assert src == "eastmoney_bid_ask"
        assert rows is not None
        mock_tx.assert_not_called()


def test_providers_reexports_match_fetch_realtime() -> None:
    from plugins.data_collection import providers as prov
    from plugins.data_collection.stock import fetch_realtime as fr

    assert prov.STOCK_REALTIME_CHAIN_ORDER == fr.STOCK_REALTIME_CHAIN_ORDER
    assert prov.run_stock_realtime_chain is fr.run_stock_realtime_chain


# --- 股票日线：Baostock 路径 ---


def test_fetch_single_stock_historical_uses_baostock_when_mootdx_off() -> None:
    with (
        patch(
            "plugins.data_collection.stock.fetch_historical.CACHE_AVAILABLE",
            False,
        ),
        patch(
            "plugins.data_collection.stock.fetch_historical.MOOTDX_AVAILABLE",
            False,
        ),
        patch(
            "plugins.data_collection.stock.fetch_historical.BAOSTOCK_AVAILABLE",
            True,
        ),
        patch(
            "plugins.data_collection.stock.fetch_historical._fetch_stock_daily_baostock",
        ) as mock_bs,
    ):
        mock_bs.return_value = pd.DataFrame(
            {
                "日期": ["2025-01-02"],
                "开盘": [10.0],
                "收盘": [10.5],
                "最高": [10.6],
                "最低": [9.9],
                "成交量": [1e6],
                "成交额": [1e7],
            }
        )
        from plugins.data_collection.stock.fetch_historical import (
            fetch_single_stock_historical,
        )

        df, src = fetch_single_stock_historical(
            "600000",
            start_date="2025-01-01",
            end_date="2025-01-10",
            use_cache=False,
        )
        assert src == "baostock"
        assert df is not None and not df.empty
        mock_bs.assert_called_once()


# --- 股票分钟：minute_source_preference ---


def test_minute_eastmoney_preference_calls_eastmoney_before_sina() -> None:
    """eastmoney 优先时：先尝试东财，空则再新浪（mootdx 已失败后）。"""
    order: list[str] = []

    def _mootdx(*a, **k):
        order.append("mootdx")
        return None

    def _sina(*a, **k):
        order.append("sina")
        return pd.DataFrame(
            {
                "时间": ["2025-01-02 09:31:00"],
                "开盘": [1.0],
                "收盘": [1.1],
                "最高": [1.2],
                "最低": [0.9],
                "成交量": [1000],
                "成交额": [10000.0],
            }
        )

    def _em(*a, **k):
        order.append("eastmoney")
        return None

    with (
        patch(
            "plugins.data_collection.stock.fetch_minute.CACHE_AVAILABLE",
            False,
        ),
        patch(
            "plugins.data_collection.stock.fetch_minute._fetch_stock_minute_mootdx",
            side_effect=_mootdx,
        ),
        patch(
            "plugins.data_collection.stock.fetch_minute._fetch_stock_minute_sina",
            side_effect=_sina,
        ),
        patch(
            "plugins.data_collection.stock.fetch_minute._fetch_stock_minute_eastmoney",
            side_effect=_em,
        ),
        patch(
            "plugins.data_collection.stock.fetch_minute._fetch_stock_minute_efinance",
            return_value=None,
        ),
        patch(
            "plugins.data_collection.stock.fetch_minute.AKSHARE_AVAILABLE",
            True,
        ),
        patch(
            "plugins.data_collection.stock.fetch_minute.EFINANCE_AVAILABLE",
            True,
        ),
    ):
        from plugins.data_collection.stock.fetch_minute import fetch_single_stock_minute

        df, src = fetch_single_stock_minute(
            "600000",
            period="5",
            start_date="2025-01-02",
            end_date="2025-01-02",
            use_cache=False,
            minute_source_preference="eastmoney",
        )
        assert src == "sina_akshare"
        assert df is not None
        assert order[0] == "mootdx"
        assert order.index("eastmoney") < order.index("sina")


# --- 期权合约：expiry_months_queried ---


def test_get_option_contracts_includes_expiry_months_queried() -> None:
    months = ["202502", "202503"]
    call_df = pd.DataFrame({"c": ["10000001"]})
    put_df = pd.DataFrame({"c": ["10000002"]})

    with patch(
        "plugins.data_collection.utils.get_contracts.ak.option_sse_list_sina",
        return_value=months,
    ), patch(
        "plugins.data_collection.utils.get_contracts.ak.option_sse_codes_sina",
        side_effect=[call_df, put_df, call_df, put_df],
    ):
        from plugins.data_collection.utils.get_contracts import get_option_contracts

        out = get_option_contracts(underlying="510300", option_type="all")
        assert out["success"] is True
        data = out["data"]
        assert "expiry_months_queried" in data
        assert data["expiry_months_queried"] == months[:2]


# --- ETF IOPV ---


def test_fetch_etf_iopv_snapshot_filters_row() -> None:
    # Note: data_collection implementation may change its primary provider.
    # This test only asserts that the function can filter the target row and returns
    # a structured payload without forcing a specific upstream.
    spot = pd.DataFrame(
        [
            {
                "基金代码": "510300",
                "基金简称": "沪深300ETF",
                "最新价": 4.5,
            }
        ]
    )

    with patch("plugins.data_collection.etf.fetch_realtime.ak.fund_etf_spot_ths", return_value=spot):
        from plugins.data_collection.etf.fetch_realtime import fetch_etf_iopv_snapshot

        r = fetch_etf_iopv_snapshot("510300")
        assert r["success"] is True
        d = r["data"]
        assert d["code"] == "510300"
        assert d["found"] is True


# --- CLI 冒烟（可访问外网时拉数；失败时仍返回结构化 JSON） ---


@pytest.mark.parametrize(
    "tool,args,keys",
    [
        (
            "tool_fetch_stock_realtime",
            {"stock_code": "600000", "mode": "test"},
            ("success", "message", "source"),
        ),
        (
            "tool_fetch_stock_historical",
            {
                "stock_code": "600000",
                "period": "daily",
                "start_date": "2025-01-01",
                "end_date": "2025-01-15",
                "use_cache": False,
            },
            ("success", "message"),
        ),
        (
            "tool_fetch_stock_minute",
            {
                "stock_code": "600000",
                "period": "5",
                "lookback_days": 2,
                "mode": "test",
                "use_cache": False,
                "minute_source_preference": "auto",
            },
            ("success", "message"),
        ),
        (
            "tool_fetch_etf_iopv_snapshot",
            {"etf_code": "510300"},
            ("success", "message", "source"),
        ),
        (
            "tool_get_option_contracts",
            {"underlying": "510300", "option_type": "all"},
            ("success", "message"),
        ),
    ],
)
def test_data_collection_tools_cli_smoke(
    tool: str,
    args: dict,
    keys: tuple,
) -> None:
    out = _run_tool_cli(tool, args)
    assert isinstance(out, dict)
    for k in keys:
        assert k in out


def test_index_realtime_supports_kc50_and_chinext50_codes() -> None:
    from plugins.data_collection.index import fetch_realtime as mod

    # Only verify whitelist/mapping acceptance here; force both providers off to avoid network.
    with patch.object(mod, "AKSHARE_AVAILABLE", False), patch.object(mod, "MOOTDX_AVAILABLE", False):
        out = mod.fetch_index_realtime(index_code="000688,399673", mode="test")

    assert out["success"] is False
    assert "需要 mootdx 或 akshare" in str(out.get("message") or "")
    # If codes were still not whitelisted, message would be "不支持的指数代码".
    assert "不支持的指数代码" not in str(out.get("message") or "")
