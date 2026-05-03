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


def test_tool_fetch_index_data_smoke() -> None:
    """merged 指数入口（实现经 plugins.data_collection 符号链接）。"""
    out = _run_tool(
        "tool_fetch_index_data",
        {"data_type": "historical", "index_code": "000300", "start_date": "20260101", "end_date": "20260110"},
    )
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


def test_tool_run_data_cache_job_smoke() -> None:
    """notify=False 避免强依赖飞书；仍可能访问数据源。"""
    out = _run_tool(
        "tool_run_data_cache_job",
        {"job": "intraday_minute", "throttle_stock": True, "notify": False},
    )
    assert isinstance(out, dict)
    assert "success" in out
    assert "collection_success" in out


def test_tool_screen_equity_factors_smoke() -> None:
    """多因子选股单入口：小样本亦须返回结构化 envelope。"""
    out = _run_tool(
        "tool_screen_equity_factors",
        {
            "universe": "custom",
            "custom_symbols": "600000",
            "top_n": 1,
            "max_universe_size": 1,
            "factors": ["reversal_5d"],
            "max_concurrent_fetch": 1,
        },
    )
    assert isinstance(out, dict)
    assert "success" in out
    assert "elapsed_ms" in out
    assert "plugin_version" in out
    if out.get("success"):
        assert "quality_score" in out
        assert "config_hash" in out
        assert isinstance(out.get("data"), list)


def test_tool_screen_by_factors_alias_smoke() -> None:
    out = _run_tool(
        "tool_screen_by_factors",
        {
            "universe": "custom",
            "custom_symbols": "600000",
            "top_n": 1,
            "max_universe_size": 1,
            "factors": ["reversal_5d"],
            "max_concurrent_fetch": 1,
        },
    )
    assert isinstance(out, dict)
    assert "success" in out


def test_tool_plugin_catalog_digest_smoke() -> None:
    out = _run_tool("tool_plugin_catalog_digest", {})
    assert out.get("success") is True
    assert isinstance(out.get("data"), dict)
    assert "source_chains" in out["data"]


def test_tool_resolve_symbol_smoke() -> None:
    out = _run_tool("tool_resolve_symbol", {"symbol": "sh600519"})
    assert out.get("success") is True
    assert out["data"]["canonical_code"] == "600519"

