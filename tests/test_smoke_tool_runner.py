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


def test_tool_quantitative_screening_valuation_smoke() -> None:
    """量化选股：缓存不足时也应返回结构化结果。"""
    out = _run_tool(
        "tool_quantitative_screening",
        {"candidates": "510300,510500", "lookback_days": 20, "universe": "etf", "top_k": 2},
    )
    assert isinstance(out, dict)
    assert out.get("status") in {"success", "error"}
    if out.get("status") == "success":
        scores = out.get("scores", [])
        assert len(scores) >= 1
        for item in scores:
            assert "symbol" in item
            assert "factors" in item
            assert "valuation" in item["factors"]
            assert "raw" in item["factors"]["valuation"]
            # ETF 未请求财务，raw 应为 999
            assert item["factors"]["valuation"]["raw"] == 999.0

