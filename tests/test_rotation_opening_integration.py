from __future__ import annotations

from plugins.notification.run_opening_analysis import (
    _build_rotation_candidate_union,
    _build_rotation_suggestions,
    _validate_rotation_opening,
)
from plugins.notification.send_daily_report import _format_daily_report


def test_rotation_candidate_union_merges_rps_and_three_factor() -> None:
    payload = {
        "legacy_views": {
            "rps_recommendations": [
                {"rank": 1, "etf_code": "159997", "etf_name": "电子ETF", "composite_score": 0.86},
                {"rank": 2, "etf_code": "512200", "etf_name": "地产ETF", "composite_score": 0.68},
            ],
            "three_factor_top5": [
                {"rank": 1, "symbol": "515880", "name": "通信ETF", "score": 0.74},
                {"rank": 2, "symbol": "512200", "name": "地产ETF", "score": 0.67},
            ],
        }
    }
    rows = _build_rotation_candidate_union(payload, max_candidates=10)
    codes = [str(x.get("etf_code") or "") for x in rows]
    assert "159997" in codes
    assert "512200" in codes
    assert "515880" in codes
    merged = next(x for x in rows if str(x.get("etf_code")) == "512200")
    assert merged.get("from_rps") is True
    assert merged.get("from_three_factor") is True


def test_rotation_validation_and_suggestions_stop_gate() -> None:
    candidates = [{"etf_code": "159997", "etf_name": "电子ETF", "rotation_score": 0.86, "rotation_rank": 1}]
    realtime = [{"code": "159997", "change_pct": 1.2, "volume_ratio": 1.35}]
    cfg = {
        "open_change_strong_threshold": 0.5,
        "open_change_weak_threshold": -1.0,
        "volume_ratio_strong_threshold": 1.2,
        "volume_ratio_weak_threshold": 0.7,
        "observe_band_pct": 0.3,
        "signal_position_multiplier": {"STRONG": 1.0, "CAUTIOUS": 0.5, "OBSERVE": 0.0, "WEAK": 0.0, "NEUTRAL": 0.0},
    }
    validations, missing = _validate_rotation_opening(candidates, realtime, cfg)
    assert not missing
    assert validations[0]["signal"] == "STRONG"
    suggestions = _build_rotation_suggestions(validations, market_gate="STOP", cfg=cfg)
    assert suggestions["market_gate"] == "STOP"
    assert suggestions["main_actions"] == []
    assert any("STOP" in str(x) for x in suggestions["risk_controls"])


def test_opening_report_rotation_section_degraded_notice() -> None:
    rd = {
        "report_type": "opening",
        "opening_report_variant": "realtime",
        "generated_at": "2026-05-01 21:20:00",
        "runtime_context": {"is_opening_window": False, "snapshot_time": "2026-05-01 21:20:00"},
        "analysis": {"overall_trend": "偏弱", "trend_strength": -0.2},
        "rotation_validation_quality": {"quality_status": "degraded", "degraded_reason": "rotation_latest_missing"},
        "rotation_trading_suggestions": {"market_gate": "STOP", "main_actions": [], "observe_list": [], "risk_controls": []},
        "rotation_data_freshness": {"note": "轮动数据基准：N/A；开盘验证基于当日实时行情。"},
    }
    _title, body = _format_daily_report(report_data=rd, report_date=None)
    assert "### 七、轮动推荐ETF开盘验证与当日建议" in body
    assert "本栏目暂不可用（仅观察）" in body

