"""
Rule 适配器：将现有可执行工具输出转为 SignalCandidate。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from strategy_engine.schemas import SignalCandidate


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _normalize_strength(val: Any) -> float:
    """Map signal_strength / trend to -1..1."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        v = float(val)
        if -1.0 <= v <= 1.0:
            return v
        if 0.0 <= v <= 1.0:
            return v
        return _clamp(v / 100.0, -1.0, 1.0)
    s = str(val).strip().lower()
    if s in ("high", "strong", "强"):
        return 0.75
    if s in ("medium", "mid", "中"):
        return 0.5
    if s in ("low", "weak", "弱"):
        return 0.25
    return 0.0


def _map_signal_type_to_direction(signal_type: Optional[str]) -> str:
    if signal_type is None:
        return "neutral"
    s = str(signal_type).strip().lower()
    if s in ("buy", "long", "call", "b", "long_signal", "trend_follow", "trend_following"):
        return "long"
    if s in ("sell", "short", "put", "short_signal"):
        return "short"
    if "trend" in s and "follow" in s:
        return "long"
    if "多" in s and "空" not in s:
        return "long"
    if "空" in s and "多" not in s:
        return "short"
    return "neutral"


def _direction_to_score(direction: str, strength: float) -> float:
    if direction == "long":
        return abs(strength)
    if direction == "short":
        return -abs(strength)
    return 0.0


def collect_from_src_signal_generation(
    underlying: str,
    inputs_hash: str,
    mode: str = "production",
) -> List[SignalCandidate]:
    """调用 src.signal_generation.tool_generate_signals。"""
    out: List[SignalCandidate] = []
    try:
        from src.signal_generation import tool_generate_signals

        raw = tool_generate_signals(underlying=str(underlying), mode=mode)
    except Exception as e:
        return [
            SignalCandidate(
                strategy_id="src_signal_generation",
                symbol=str(underlying),
                direction="neutral",
                score=0.0,
                confidence=0.0,
                rationale=f"src_signal_generation import/run error: {e}",
                rationale_refs=["error"],
                inputs_hash=inputs_hash,
                metadata={"source": "rule", "provider": "src_signal_generation", "ok": False},
            )
        ]

    if not isinstance(raw, dict) or not raw.get("success"):
        msg = (raw or {}).get("message", "unknown") if isinstance(raw, dict) else "invalid response"
        out.append(
            SignalCandidate(
                strategy_id="src_signal_generation",
                symbol=str(underlying),
                direction="neutral",
                score=0.0,
                confidence=0.15,
                rationale=str(msg)[:500],
                rationale_refs=["no_success"],
                inputs_hash=inputs_hash,
                metadata={"source": "rule", "provider": "src_signal_generation", "ok": False},
            )
        )
        return out

    data = raw.get("data") or {}
    signals = data.get("signals") if isinstance(data.get("signals"), list) else []
    stype = data.get("signal_type")
    conf = data.get("signal_confidence")
    if conf is None:
        conf = data.get("signal_strength")
    conf_f = _clamp(float(conf) if isinstance(conf, (int, float)) else abs(_normalize_strength(conf)), 0.0, 1.0)
    direction = _map_signal_type_to_direction(stype)
    strength = _normalize_strength(data.get("signal_strength"))
    score = _direction_to_score(direction, strength if strength != 0 else conf_f)

    refs: List[str] = []
    if signals:
        for i, sig in enumerate(signals[:5]):
            if isinstance(sig, dict):
                refs.append(json.dumps(sig, ensure_ascii=False, default=str)[:400])
    else:
        refs.append("aggregated_top_level_signal")

    rationale_refs = refs[:5] if refs else ["src.signal_generation"]

    out.append(
        SignalCandidate(
            strategy_id="src_signal_generation",
            symbol=str(underlying),
            direction=SignalCandidate.direction_from_hold(direction),
            score=_clamp(score, -1.0, 1.0),
            confidence=conf_f if conf_f > 0 else 0.35,
            rationale=str(raw.get("message", ""))[:300],
            rationale_refs=rationale_refs,
            inputs_hash=inputs_hash,
            features={"signal_count": len(signals), "trend_strength": data.get("trend_strength")},
            metadata={"source": "rule", "provider": "src_signal_generation", "ok": True},
            timestamp=str(data.get("signal_id", ""))[:20],
        )
    )
    return out


def collect_from_trend_following(
    etf_symbol: str,
    index_code: str,
    inputs_hash: str,
) -> List[SignalCandidate]:
    from analysis.etf_trend_tracking import tool_generate_trend_following_signal

    raw = tool_generate_trend_following_signal(etf_symbol=str(etf_symbol), index_code=str(index_code))
    if not isinstance(raw, dict) or not raw.get("success"):
        msg = (raw or {}).get("message", "unknown") if isinstance(raw, dict) else "invalid"
        return [
            SignalCandidate(
                strategy_id="etf_trend_following",
                symbol=str(etf_symbol),
                direction="neutral",
                score=0.0,
                confidence=0.1,
                rationale=str(msg)[:500],
                rationale_refs=["trend_provider_error"],
                inputs_hash=inputs_hash,
                metadata={"source": "rule", "provider": "etf_trend_following", "ok": False},
            )
        ]

    data = raw.get("data") or {}
    stype = data.get("signal_type")
    direction = _map_signal_type_to_direction(stype)
    if stype is None or direction == "neutral":
        direction = "neutral"
    conf = float(data.get("confidence") or 0.35)
    conf = _clamp(conf, 0.0, 1.0)
    strength = _normalize_strength(data.get("signal_strength"))
    if direction == "neutral":
        score = 0.0
    else:
        score = _direction_to_score(direction, strength if strength else conf)

    refs: List[str] = [
        f"consistency={data.get('consistency')}",
        f"reason={data.get('reason', '')}",
    ]
    try:
        from strategy_config import get_strategy_config

        cfg = get_strategy_config("trend_following_510300")
        entry = (cfg.get("triggers") or {}).get("entry") or []
        if isinstance(entry, list):
            refs = [str(x) for x in entry[:4]] + refs
    except Exception:
        pass

    return [
        SignalCandidate(
            strategy_id="etf_trend_following",
            symbol=str(etf_symbol),
            direction=SignalCandidate.direction_from_hold(direction),
            score=_clamp(score, -1.0, 1.0),
            confidence=conf,
            rationale=str(raw.get("message", ""))[:300],
            rationale_refs=refs,
            inputs_hash=inputs_hash,
            features={"index_code": str(index_code)},
            metadata={"source": "rule", "provider": "etf_trend_following", "ok": True},
            timestamp=str(data.get("timestamp", "")),
        )
    ]
