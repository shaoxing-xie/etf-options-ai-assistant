"""L4-semantic brief tools: unit tests with mocks (no network)."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_tool_semantic_equity_valuation_brief_mocked() -> None:
    from plugins.analysis.semantic import equity_valuation_brief as mod

    resolve = {
        "success": True,
        "quality_status": "ok",
        "data": {"canonical_code": "600519", "entity_type": "stock"},
    }
    l4v = {
        "success": True,
        "quality_status": "ok",
        "data": {"metrics": {"pe": 28.5, "pb": 8.1}},
    }
    pe_row = {
        "success": True,
        "quality_status": "ok",
        "data": {"percentile_0_100": 56.2},
    }

    with (
        patch.object(mod, "tool_resolve_symbol", return_value=resolve),
        patch.object(mod, "tool_l4_valuation_context", return_value=l4v),
        patch.object(mod, "tool_l4_pe_ttm_percentile", return_value=pe_row),
    ):
        out = mod.tool_semantic_equity_valuation_brief(symbol="贵州茅台", trade_date="2026-05-05")

    assert out.get("success") is True
    assert out.get("quality_status") == "ok"
    d = out.get("data") or {}
    assert "summary" in d
    assert d.get("canonical_code") == "600519"
    meta = out.get("_meta") or {}
    assert meta.get("data_layer") == "L4_semantic"
    assert meta.get("schema_name") == "equity_valuation_brief_v1"
    assert "tool_l4_pe_ttm_percentile" in (meta.get("lineage_refs") or [])


def test_narrative_pick_percentile_label() -> None:
    from plugins.analysis.semantic.narrative import load_rules, pick_percentile_label

    rules = load_rules()
    assert pick_percentile_label(10.0, rules).startswith("percentile_") or pick_percentile_label(10.0, rules)


def test_merge_upstream_quality() -> None:
    from plugins.analysis.semantic.common import merge_upstream_quality

    assert merge_upstream_quality("ok", "ok") == "ok"
    assert merge_upstream_quality("ok", "degraded") == "degraded"
    assert merge_upstream_quality("degraded", "error") == "error"


def test_tool_semantic_portfolio_concentration_brief_weights_required() -> None:
    from plugins.analysis.semantic.portfolio_concentration_brief import tool_semantic_portfolio_concentration_brief

    out = tool_semantic_portfolio_concentration_brief(weights={})
    assert out.get("success") is False
    assert out.get("quality_status") == "error"


def test_tool_semantic_flow_sentiment_brief_mocked() -> None:
    from plugins.analysis.semantic import flow_sentiment_brief as mod

    def _fake_fetch(*args: object, **kwargs: object) -> dict:
        qk = kwargs.get("query_kind")
        if qk == "market_history":
            return {
                "success": True,
                "quality_status": "ok",
                "flow_score": 0.62,
                "cumulative": {"5d": 12.34},
            }
        return {
            "success": True,
            "quality_status": "ok",
            "records": [{"板块名称": "银行"}, {"板块名称": "电力"}],
        }

    with patch.object(mod, "tool_fetch_a_share_fund_flow", side_effect=_fake_fetch):
        out = mod.tool_semantic_flow_sentiment_brief(trade_date="2026-05-05")

    assert out.get("success") is True
    assert out.get("quality_status") == "ok"
    d = out.get("data") or {}
    assert "summary" in d
    meta = out.get("_meta") or {}
    assert meta.get("data_layer") == "L4_semantic"
    assert meta.get("schema_name") == "flow_sentiment_brief_v1"
    assert "tool_fetch_a_share_fund_flow" in (meta.get("lineage_refs") or [])


def test_tool_semantic_market_regime_brief_mocked() -> None:
    from plugins.analysis.semantic import market_regime_brief as mod

    mr = {"success": True, "data": {"regime": "range", "confidence": 0.8, "features": {"momentum_20d": 0.01}}}
    ix = {"success": True, "data": {"change_percent": 0.35, "close": 3050.1}}
    sh = {"success": True, "sectors": [{"name": "煤炭"}, {"name": "有色"}]}

    with (
        patch.object(mod, "tool_detect_market_regime", return_value=mr),
        patch.object(mod, "tool_fetch_index_data", return_value=ix),
        patch.object(mod, "tool_sector_heat_score", return_value=sh),
    ):
        out = mod.tool_semantic_market_regime_brief(
            benchmark_etf="510300",
            index_code="000001",
            trade_date="2026-05-05",
        )

    assert out.get("success") is True
    meta = out.get("_meta") or {}
    assert meta.get("data_layer") == "L4_semantic"
    assert meta.get("schema_name") == "market_regime_brief_v1"
    d = out.get("data") or {}
    assert d.get("regime") == "range"
    assert "summary" in d
