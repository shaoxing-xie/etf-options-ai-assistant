"""
Rule 适配器：将现有可执行工具输出转为 SignalCandidate。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional

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


def _src_option_features(data: Dict[str, Any]) -> Dict[str, Any]:
    """从期权信号 ``data`` 抽取可审计、体积可控的字段写入 ``SignalCandidate.features``。"""
    feat: Dict[str, Any] = {}
    for k in ("asset_class", "signal_id", "signal_type"):
        if data.get(k) is not None:
            feat[k] = data.get(k)
    sym = data.get("symbol")
    if sym is not None:
        feat["underlying_symbol"] = sym
    meta = data.get("meta")
    if isinstance(meta, dict):
        feat["meta_keys"] = list(meta.keys())
        for mk in ("index_symbol", "underlying", "resolved_name", "option_chain_hint"):
            if meta.get(mk) is not None:
                feat[mk] = meta[mk]
    signals = data.get("signals")
    if isinstance(signals, list) and signals:
        first = next((s for s in signals if isinstance(s, dict)), None)
        if first:
            for k in (
                "contract_code",
                "strike_price",
                "strike",
                "option_type",
                "risk_reward_ratio",
                "risk_reward",
                "etf_position",
                "position_pct",
                "volatility_range",
                "expected_move",
                "iv_rank",
                "delta",
                "gamma",
                "vega",
            ):
                if first.get(k) is not None:
                    feat[f"primary_signal_{k}"] = first.get(k)
    return feat


def _trend_features(data: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "consistency": data.get("consistency"),
        "reason": data.get("reason"),
        "signal_type_raw": data.get("signal_type"),
        "etf_symbol": data.get("etf_symbol"),
        "index_code": data.get("index_code"),
    }
    src = raw.get("source")
    if src is not None:
        out["source"] = src
    return {k: v for k, v in out.items() if v is not None}


def collect_from_src_signal_generation(
    underlying: str,
    inputs_hash: str,
    mode: str = "production",
) -> List[SignalCandidate]:
    """调用 src.signal_generation.tool_generate_option_trading_signals（与 tool_generate_signals 等价）。"""
    out: List[SignalCandidate] = []
    try:
        from src.signal_generation import tool_generate_option_trading_signals

        raw = tool_generate_option_trading_signals(underlying=str(underlying), mode=mode)
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

    feat = {"signal_count": len(signals), "trend_strength": data.get("trend_strength")}
    feat.update(_src_option_features(data))

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
            features=feat,
            metadata={"source": "rule", "provider": "src_signal_generation", "ok": True},
            timestamp=str(data.get("signal_id", ""))[:20],
        )
    )
    return out


def _trend_following_entry_refs(etf_symbol: str, index_code: str) -> List[str]:
    """
    从 strategy_config 取趋势策略 entry 描述作 rationale_refs。
    优先 trend_following_{etf_symbol}；若无则回退 trend_following_510300，
    并把文案中的 510300/000300 替换为当前标的与指数，避免多 ETF 组合时张冠李戴。
    """
    try:
        from strategy_config import get_strategy_config

        sid = f"trend_following_{etf_symbol}"
        try:
            cfg = get_strategy_config(sid)
        except KeyError:
            cfg = get_strategy_config("trend_following_510300")
        entry = (cfg.get("triggers") or {}).get("entry") or []
        if not isinstance(entry, list):
            return []

        def _rewrite(s: Any) -> str:
            t = str(s)
            t = t.replace("510300", str(etf_symbol))
            t = t.replace("000300", str(index_code))
            return t

        return [_rewrite(x) for x in entry[:4]]
    except Exception:
        return []


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

    refs: List[str] = _trend_following_entry_refs(etf_symbol, index_code) + [
        f"consistency={data.get('consistency')}",
        f"reason={data.get('reason', '')}",
    ]

    tfeat = _trend_features(data, raw)
    tfeat.setdefault("index_code", str(index_code))

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
            features=tfeat,
            metadata={"source": "rule", "provider": "etf_trend_following", "ok": True},
            timestamp=str(data.get("timestamp", "")),
        )
    ]


def collect_from_internal_chart_alert(
    symbol: str,
    inputs_hash: str,
    lookback_minutes: int = 120,
) -> List[SignalCandidate]:
    """Collect recent internal chart alerts from jsonl event store."""
    events_file = Path(__file__).resolve().parents[2] / "data" / "alerts" / "internal_alert_events.jsonl"
    if not events_file.is_file():
        return []

    now = datetime.now()
    rows: List[dict[str, Any]] = []
    for line in events_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("source") != "internal_chart_alert":
            continue
        if obj.get("symbol") != str(symbol):
            continue
        if obj.get("status") != "triggered":
            continue
        ts_raw = obj.get("trigger_ts")
        if not isinstance(ts_raw, str):
            continue
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError:
            continue
        if now - ts > timedelta(minutes=lookback_minutes):
            continue
        rows.append(obj)

    if not rows:
        return []
    latest = rows[-1]
    snapshot = latest.get("condition_snapshot") if isinstance(latest.get("condition_snapshot"), dict) else {}
    metric = str(snapshot.get("metric", "")).lower()
    operator = str(snapshot.get("operator", ""))
    actual = snapshot.get("actual")
    target = snapshot.get("value")

    direction = "neutral"
    score = 0.0
    confidence = 0.4
    if metric == "rsi":
        if isinstance(actual, (int, float)):
            v = float(actual)
            if v <= 30:
                direction = "long"
                score = 0.55
                confidence = 0.6
            elif v >= 70:
                direction = "short"
                score = -0.55
                confidence = 0.6

    return [
        SignalCandidate(
            strategy_id="internal_chart_alert",
            symbol=str(symbol),
            direction=direction,
            score=score,
            confidence=confidence,
            rationale=f"internal alert triggered: {metric} {operator} {target}, actual={actual}",
            rationale_refs=[json.dumps(latest, ensure_ascii=False, default=str)[:400]],
            inputs_hash=inputs_hash,
            features={
                "rule_id": latest.get("rule_id"),
                "group": latest.get("group"),
                "priority": latest.get("priority"),
                "condition_snapshot": snapshot,
            },
            metadata={"source": "rule", "provider": "internal_chart_alert", "ok": True},
            timestamp=str(latest.get("trigger_ts", "")),
        )
    ]
