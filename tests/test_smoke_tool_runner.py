import json
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


def _run_tool(tool: str, args: dict) -> dict:
    runner = BASE_DIR / "tool_runner.py"
    proc = subprocess.run(
        [str(BASE_DIR / ".venv" / "bin" / "python"), str(runner), tool, json.dumps(args, ensure_ascii=False)],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    out = proc.stdout.strip()
    assert out
    return json.loads(out)


def test_tool_read_market_data_smoke() -> None:
    out = _run_tool("tool_read_market_data", {"data_type": "etf_daily", "symbol": "510300"})
    assert isinstance(out, dict)
    assert "success" in out


def test_tool_send_feishu_notification_dry_smoke() -> None:
    # This is a dry smoke: the tool returns structured result even if webhook missing.
    out = _run_tool(
        "tool_send_feishu_notification",
        {"notification_type": "message", "title": "[TEST] smoke", "message": "hello"},
    )
    assert isinstance(out, dict)
    assert "success" in out


def test_tool_detect_market_regime_smoke() -> None:
    out = _run_tool("tool_detect_market_regime", {"symbol": "510300", "mode": "test"})
    assert isinstance(out, dict)
    # tool may fail if cache empty; still must be well-formed
    assert "success" in out


def test_tool_etf_rotation_research_smoke() -> None:
    # Use a single symbol to reduce dependency on full ETF pool cache.
    out = _run_tool(
        "tool_etf_rotation_research",
        {"etf_pool": "510300", "lookback_days": 180, "top_k": 1, "mode": "test"},
    )
    assert isinstance(out, dict)
    assert "success" in out


def test_tool_strategy_research_smoke() -> None:
    out = _run_tool(
        "tool_strategy_research",
        {"lookback_days": 60, "strategies": "trend_following", "adjustment_rate": 0.1, "mode": "test"},
    )
    assert isinstance(out, dict)
    assert "success" in out


def test_tool_fetch_stock_financials_smoke() -> None:
    """财务工具：仅校验返回结构，不依赖网络成功。"""
    out = _run_tool("tool_fetch_stock_financials", {"symbols": "600000,000001"})
    assert isinstance(out, dict)
    assert out.get("status") in ("success", "error")
    assert "financials" in out
    financials = out["financials"]
    assert isinstance(financials, list)
    for rec in financials:
        assert "symbol" in rec
        assert "success" in rec
        assert rec.get("pe_ttm") is None or isinstance(rec["pe_ttm"], (int, float))
        assert "error" in rec or "pe_ttm" in rec


def test_tool_stock_data_fetcher_smoke() -> None:
    """个股聚合工具：只校验结构，不强依赖网络成功。"""
    out = _run_tool(
        "tool_stock_data_fetcher",
        {
            "action": "fetch",
            "symbols": "600000,000001",
            "data_types": ["realtime", "daily", "minute"],
            "minute_period": "5",
            "lookback_days": 5,
            "include_analysis": False,
            "mode": "test",
            "indicators": ["ma", "macd", "rsi", "bollinger"],
        },
    )
    assert isinstance(out, dict)
    assert "success" in out
    assert "data" in out
    assert "count" in out


def test_tool_stock_monitor_smoke() -> None:
    """个股监控工具：仅校验可执行与结构，不触发真实通知。"""
    out = _run_tool(
        "tool_stock_monitor",
        {
            "action": "run_once",
            "watchlist": ["600000"],
            "triggers": [{"type": "price_change", "pct": 1.0}],
            "output_channel": "dingtalk",
            "cooldown_minutes": 0,
            "mode": "test",
        },
    )
    assert isinstance(out, dict)
    assert out.get("success") is True
    assert isinstance(out.get("data"), dict)
    assert "fired" in out["data"]


def test_tool_quantitative_screening_valuation_smoke() -> None:
    """量化选股：ETF 候选时 valuation 因子存在且为 999（未拉财务）。"""
    out = _run_tool(
        "tool_quantitative_screening",
        {"candidates": "510300,510500", "lookback_days": 20, "universe": "etf", "top_k": 2},
    )
    assert isinstance(out, dict)
    assert out.get("status") == "success"
    scores = out.get("scores", [])
    assert len(scores) >= 1
    for item in scores:
        assert "symbol" in item
        assert "factors" in item
        assert "valuation" in item["factors"]
        assert "raw" in item["factors"]["valuation"]
        # ETF 未请求财务，raw 应为 999
        assert item["factors"]["valuation"]["raw"] == 999.0

