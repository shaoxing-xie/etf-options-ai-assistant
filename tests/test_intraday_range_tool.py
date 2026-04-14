"""
tool_predict_intraday_range：补算路径不再使用日线降级；失败时返回 data.error_code。
集成测：可选走 tool_runner；契约测：mock 覆盖错误码。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
def test_tool_predict_intraday_range_live_510300_structure() -> None:
    """有网络/行情时：成功则含 data.lower_bound；失败则含 error_code（不设必须为成功）。"""
    out = _run_tool_via_subprocess("tool_predict_intraday_range", {"underlying": "510300"})
    assert isinstance(out, dict)
    assert "success" in out
    if out.get("success"):
        assert "data" in out and isinstance(out["data"], dict)
        assert "lower_bound" in out["data"] and "upper_bound" in out["data"]
    else:
        err = (out.get("data") or {}).get("error_code")
        assert err in (
            "INTRADAY_SPOT_PRICE_UNAVAILABLE",
            "INTRADAY_MINUTE_DATA_UNAVAILABLE",
            "INTRADAY_MINUTE_CALC_INVALID",
            None,
        )


def _resolved_etf(code: str = "510300") -> SimpleNamespace:
    return SimpleNamespace(ok=True, code=code, asset_type="etf", error=None, candidates=None)


@patch("src.prediction_recorder.record_prediction", MagicMock())
@patch("src.logger_config.get_module_logger", lambda _: MagicMock())
def test_intraday_spot_unavailable_error_code() -> None:
    from plugins.analysis.intraday_range import tool_predict_intraday_range

    with patch("plugins.analysis.intraday_range.resolve_volatility_underlying", return_value=_resolved_etf()):
        with patch("src.config_loader.load_system_config", return_value={}):
            with patch(
                "src.on_demand_predictor.predict_etf_volatility_range_on_demand",
                return_value={"success": False, "error": "forced fail"},
            ):
                with patch(
                    "plugins.data_collection.etf.fetch_realtime.tool_fetch_etf_realtime",
                    return_value={"success": False},
                ):
                    out = tool_predict_intraday_range(underlying="510300")
    assert out["success"] is False
    assert out["data"]["error_code"] == "INTRADAY_SPOT_PRICE_UNAVAILABLE"
    assert "不使用日线" in out["message"] or "实时行情" in out["message"]


@patch("src.prediction_recorder.record_prediction", MagicMock())
@patch("src.logger_config.get_module_logger", lambda _: MagicMock())
def test_intraday_minute_data_unavailable_error_code() -> None:
    from plugins.analysis.intraday_range import tool_predict_intraday_range

    with patch("plugins.analysis.intraday_range.resolve_volatility_underlying", return_value=_resolved_etf()):
        with patch("src.config_loader.load_system_config", return_value={}):
            with patch(
                "src.on_demand_predictor.predict_etf_volatility_range_on_demand",
                return_value={"success": False},
            ):
                with patch(
                    "plugins.data_collection.etf.fetch_realtime.tool_fetch_etf_realtime",
                    return_value={"success": True, "data": {"current_price": 4.5}},
                ):
                    with patch(
                        "src.volatility_range.get_remaining_trading_time",
                        return_value=60,
                    ):
                        with patch(
                            "src.data_collector.fetch_etf_minute_data_with_fallback",
                            return_value=(None, None),
                        ):
                            out = tool_predict_intraday_range(underlying="510300")
    assert out["success"] is False
    assert out["data"]["error_code"] == "INTRADAY_MINUTE_DATA_UNAVAILABLE"
    assert "分钟" in out["message"] and "日线降级" in out["message"]


@patch("src.prediction_recorder.record_prediction", MagicMock())
@patch("src.logger_config.get_module_logger", lambda _: MagicMock())
def test_intraday_minute_calc_invalid_error_code() -> None:
    import pandas as pd

    from plugins.analysis.intraday_range import tool_predict_intraday_range

    df = pd.DataFrame({"收盘": [4.5, 4.51], "最高": [4.52, 4.53], "最低": [4.49, 4.5]})

    with patch("plugins.analysis.intraday_range.resolve_volatility_underlying", return_value=_resolved_etf()):
        with patch("src.config_loader.load_system_config", return_value={}):
            with patch(
                "src.on_demand_predictor.predict_etf_volatility_range_on_demand",
                return_value={"success": False},
            ):
                with patch(
                    "plugins.data_collection.etf.fetch_realtime.tool_fetch_etf_realtime",
                    return_value={"success": True, "data": {"current_price": 4.5}},
                ):
                    with patch("src.volatility_range.get_remaining_trading_time", return_value=60):
                        with patch(
                            "src.data_collector.fetch_etf_minute_data_with_fallback",
                            return_value=(df, df),
                        ):
                            with patch(
                                "src.volatility_range.calculate_etf_volatility_range_multi_period",
                                return_value={"upper": None, "lower": None, "confidence": 0.5},
                            ):
                                out = tool_predict_intraday_range(underlying="510300")
    assert out["success"] is False
    assert out["data"]["error_code"] == "INTRADAY_MINUTE_CALC_INVALID"
    assert "日线降级" in out["message"]


def test_no_fallback_import_in_module() -> None:
    """确保补算路径不再依赖 volatility_range_fallback。"""
    src = (BASE_DIR / "plugins" / "analysis" / "intraday_range.py").read_text(encoding="utf-8")
    assert "volatility_range_fallback" not in src
    assert "calculate_etf_volatility_range_fallback" not in src
