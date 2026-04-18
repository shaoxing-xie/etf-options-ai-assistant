from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from analysis.etf_rotation_research import tool_etf_rotation_research


def _mk_row(symbol: str, pool_type: str, score: float) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        pool_type=pool_type,
        score=score,
        legacy_score=score,
        momentum_5d=0.01,
        momentum_20d=0.02,
        momentum_60d=0.03,
        vol_20d=0.2,
        vol20_percentile=0.5,
        max_drawdown_60d=-0.08,
        win_rate_20d=0.65,
        trend_r2=0.6,
        mean_abs_corr=0.4,
        stability_score=0.5,
        above_ma=True,
        excluded=False,
        exclude_reason=None,
        soft_penalties={},
    )


def test_rotation_research_report_contains_layered_sections() -> None:
    ranked = [
        _mk_row("512480", "industry", 0.91),
        _mk_row("512010", "industry", 0.82),
        _mk_row("513120", "concept", 0.79),
        _mk_row("513130", "concept", 0.74),
    ]
    pipe = {
        "ranked_active": ranked,
        "ranked_by_pool": {"industry": ranked[:2], "concept": ranked[2:]},
        "warnings": [],
        "fallback_legacy_ranking": False,
        "correlation_matrix": None,
        "correlation_symbols": [],
        "config_snapshot": {"load_range": ["20240101", "20250101"], "correlation_mode": "penalize"},
        "errors": [],
        "data_readiness": {
            "industry_coverage": {"available": 2, "total": 2},
            "concept_coverage": {"available": 2, "total": 2},
            "degraded": False,
            "degraded_reasons": [],
            "degraded_evidence": {},
        },
    }
    with (
        patch("analysis.etf_rotation_research.load_rotation_config", return_value={"paths": {}}),
        patch("analysis.etf_rotation_research.resolve_etf_pool", return_value=[r.symbol for r in ranked]),
        patch("analysis.etf_rotation_research.run_rotation_pipeline", return_value=pipe),
        patch("analysis.etf_rotation_research.read_last_rotation_runs", return_value=[]),
    ):
        out = tool_etf_rotation_research(mode="test")
    assert out["success"] is True
    data = out["data"]
    assert "ranked_by_pool" in data
    txt = data["report_data"]["llm_summary"]
    assert "分层轮动榜" in txt
    assert "行业池 Top5" in txt
    assert "概念池 Top5" in txt
    assert "全池观察榜 Top10" in txt
    raw = data["report_data"].get("raw") or {}
    assert "pipeline" not in raw, "toolResult 不应包含全量 pipeline，避免撑爆上下文"
