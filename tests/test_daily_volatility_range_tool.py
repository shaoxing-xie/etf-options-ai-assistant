"""
tool_predict_daily_volatility_range：日频全日区间；契约测 mock；集成测可选走 tool_runner。
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parents[1]


def _run_tool_via_subprocess(tool: str, args: dict) -> dict:
    py = sys.executable
    proc = subprocess.run(
        [py, str(BASE_DIR / "tool_runner.py"), tool, json.dumps(args, ensure_ascii=False)],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
        timeout=180,
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        raise AssertionError(f"no stdout rc={proc.returncode} stderr={proc.stderr!r}")
    for line in raw.split("\n")[::-1]:
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return json.loads(raw)


@pytest.mark.integration
def test_tool_predict_daily_volatility_range_live_510300_structure() -> None:
    """有网络/行情时：成功则含 data.upper/data.lower；失败则含 error_code。"""
    out = _run_tool_via_subprocess("tool_predict_daily_volatility_range", {"underlying": "510300"})
    assert isinstance(out, dict)
    assert "success" in out
    if out.get("success"):
        assert "data" in out and isinstance(out["data"], dict)
        assert "lower" in out["data"] and "upper" in out["data"]
        assert "formatted_output" in out
    else:
        err = (out.get("data") or {}).get("error_code")
        assert err in (
            "DAILY_HISTORY_UNAVAILABLE",
            "DAILY_HISTORY_INSUFFICIENT",
            "DAILY_HV_CALC_FAILED",
            "DAILY_RANGE_DISABLED",
            None,
        )


def _fake_daily_df(rows: int) -> pd.DataFrame:
    """合成日 K（不依赖 numpy，便于在未装 numpy 的环境中收集/运行单元测）。"""
    n = rows
    random.seed(42)
    close: list[float] = [3.0]
    for _ in range(n - 1):
        close.append(close[-1] * (1.0 + random.gauss(0.0, 0.008)))
    return pd.DataFrame(
        {
            "日期": pd.date_range("2024-01-01", periods=n, freq="B"),
            "收盘": close,
            "最高": [x * 1.015 for x in close],
            "最低": [x * 0.985 for x in close],
        }
    )


def test_compute_daily_volatility_range_success_structure() -> None:
    from src.daily_volatility_range import compute_daily_volatility_range

    def _adj(b, *_a, **_k):
        return b, False, ""

    cfg = {"daily_volatility_range": {"min_data_days": 120, "fetch_lookback_days": 600}}
    with patch("src.daily_volatility_range._fetch_daily_bars", return_value=_fake_daily_df(130)):
        with patch("src.daily_volatility_range._resolve_anchor_price", return_value=3.0):
            with patch("src.daily_volatility_range._intraday_adjust_range_pct", side_effect=_adj):
                with patch("src.daily_volatility_range.get_remaining_trading_time", return_value=120):
                    out = compute_daily_volatility_range("510300", "etf", cfg)
    assert out["success"] is True
    d = out["data"]
    assert d["symbol"] == "510300"
    assert d["lower"] < d["current_price"] < d["upper"]
    assert d["range_pct"] > 0
    assert len(d["windows_used"]) == 3
    assert "weights_effective" in d


@patch("src.daily_volatility_range._fetch_daily_bars", lambda *a, **k: _fake_daily_df(50))
def test_compute_daily_history_insufficient() -> None:
    from src.daily_volatility_range import compute_daily_volatility_range

    out = compute_daily_volatility_range("510300", "etf", {})
    assert out["success"] is False
    assert out["data"]["error_code"] == "DAILY_HISTORY_INSUFFICIENT"


def test_compute_daily_disabled() -> None:
    from src.daily_volatility_range import compute_daily_volatility_range

    out = compute_daily_volatility_range(
        "510300",
        "etf",
        {"daily_volatility_range": {"enabled": False}},
    )
    assert out["success"] is False
    assert out["data"]["error_code"] == "DAILY_RANGE_DISABLED"


def test_plugin_resolve_failure() -> None:
    from plugins.analysis.daily_volatility_range import tool_predict_daily_volatility_range

    bad = SimpleNamespace(ok=False, error="ambiguous", candidates=None)
    with patch("plugins.analysis.daily_volatility_range.resolve_volatility_underlying", return_value=bad):
        out = tool_predict_daily_volatility_range(underlying="???")
    assert out["success"] is False
    assert "ambiguous" in out["message"]


@patch("src.daily_volatility_range.compute_daily_volatility_range")
def test_plugin_success_wraps_markdown(mock_compute: MagicMock) -> None:
    from plugins.analysis.daily_volatility_range import tool_predict_daily_volatility_range

    mock_compute.return_value = {
        "success": True,
        "message": "ok",
        "data": {
            "symbol": "510300",
            "asset_type": "etf",
            "current_price": 4.0,
            "lower": 3.9,
            "upper": 4.1,
            "range_pct": 2.5,
            "confidence": 0.55,
            "method": "test",
            "timestamp": "2026-01-01 10:00:00",
            "horizon": "1d",
            "target_session": "current",
            "windows_used": [5, 22, 63],
            "hv_annualized_pct": [10, 12, 14],
            "atr_pct_contribution": 1.0,
            "weights_effective": {"hv": [0.25, 0.35, 0.4], "atr": 0.2},
            "intraday_adjusted": False,
            "intraday_adjust_note": "",
            "remaining_trading_minutes_snapshot": 0,
        },
    }
    ok_res = SimpleNamespace(ok=True, code="510300", asset_type="etf", error=None, candidates=None)
    with patch("plugins.analysis.daily_volatility_range.resolve_volatility_underlying", return_value=ok_res):
        with patch("src.config_loader.load_system_config", return_value={}):
            out = tool_predict_daily_volatility_range(underlying="510300")
    assert out["success"] is True
    assert "formatted_output" in out
    assert "全日" in out["formatted_output"]
    assert "510300" in out["formatted_output"]
