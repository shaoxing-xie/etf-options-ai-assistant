"""When plugin RPS recommendations are empty, L4 maps unified_next_day into legacy recommendations."""

from __future__ import annotations

from analysis.etf_rotation_research import _synthetic_sector_recommendations_from_unified


def test_synthetic_sector_recommendations_from_unified_preserves_codes_and_scores() -> None:
    unified = [
        {
            "rank": 1,
            "etf_code": "515400",
            "etf_name": "中证煤炭ETF",
            "sector": "industry",
            "unified_score": 0.885,
            "components": {"rps_20d": None, "rps_5d": None, "volume_ratio": 1.2},
            "cautions": ["sector_rotation_recommendations_empty"],
            "explain_bullets": ["三维"],
            "allocation_pct": None,
        },
        {
            "rank": 2,
            "etf_code": "518880",
            "etf_name": "黄金ETF",
            "sector": "concept",
            "unified_score": 0.84,
            "components": {},
            "cautions": [],
            "explain_bullets": [],
            "allocation_pct": 5,
        },
    ]
    out = _synthetic_sector_recommendations_from_unified(unified)
    assert len(out) == 2
    assert out[0]["etf_code"] == "515400"
    assert out[0]["composite_score"] == 0.885
    assert out[0]["signals"]["volume_ratio"] == 1.2
    assert any("l4_legacy_projection_from_unified" in str(c) for c in out[0]["cautions"])
    assert out[1]["allocation_pct"] == 5


def test_synthetic_skips_invalid_rows() -> None:
    assert _synthetic_sector_recommendations_from_unified([{}, {"etf_code": ""}]) == []
