"""
OpenClaw 工具：聚合 Rule 策略输出并执行 Fusion。

禁止在此模块内 subprocess 调用 tool_runner。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

from strategy_engine.fusion import fuse_all_by_symbol, load_fusion_config, merge_weights
from strategy_engine.llm_strategy import generate_llm_candidates
from strategy_engine.rule_adapters import (
    collect_from_internal_chart_alert,
    collect_from_src_signal_generation,
    collect_from_trend_following,
)
from strategy_engine.schemas import FusionResult, SignalCandidate


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_openclaw_strategy_engine_config() -> Dict[str, Any]:
    p = _repo_root() / "config" / "openclaw_strategy_engine.yaml"
    if yaml is None or not p.is_file():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _persist_effective_weights(weights: Dict[str, float], rel_path: str) -> None:
    out = _repo_root() / rel_path
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "weights": {k: float(v) for k, v in weights.items()},
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "tool_strategy_engine",
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_inputs_hash(parts: Dict[str, Any]) -> str:
    canonical = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _fusion_policy_for_hash(policy: Dict[str, float]) -> Dict[str, float]:
    """与 fusion 使用的 policy 一致的可复现浮点快照（纳入 inputs_hash）。"""
    return {
        "score_threshold": round(float(policy["score_threshold"]), 10),
        "agree_ratio_min": round(float(policy["agree_ratio_min"]), 10),
        "strong_abs_score": round(float(policy["strong_abs_score"]), 10),
    }


def _strategy_weights_for_hash(weights: Dict[str, Any]) -> Dict[str, float]:
    """YAML 默认权重快照（纳入 inputs_hash）；仅改权重时与旧运行区分。"""
    out: Dict[str, float] = {}
    for k in sorted(weights.keys()):
        try:
            out[str(k)] = round(float(weights[k]), 10)
        except (TypeError, ValueError):
            continue
    return out


def _build_fusion_summary(
    candidates: List[SignalCandidate],
    fused_by_symbol: Dict[str, FusionResult],
    strong_abs_score: float,
) -> Dict[str, Any]:
    thr = float(strong_abs_score)
    return {
        "total_candidates": len(candidates),
        "fused_symbol_count": len(fused_by_symbol),
        "fused_symbols": sorted(fused_by_symbol.keys()),
        "non_neutral_fused_count": sum(1 for v in fused_by_symbol.values() if v.direction != "neutral"),
        "strong_fused_count": sum(1 for v in fused_by_symbol.values() if abs(float(v.score)) >= thr),
        "strong_abs_score_threshold": thr,
    }


def _parse_csv_tokens(s: str) -> List[str]:
    return [p.strip() for p in str(s).split(",") if p.strip()]


def _underlyings_list(underlying: str) -> List[str]:
    parts = _parse_csv_tokens(underlying)
    return parts if parts else ["510300"]


def _align_index_codes(
    underlyings: List[str],
    index_code: str,
    provider_errors: List[str],
) -> List[str]:
    raw = _parse_csv_tokens(index_code)
    n = len(underlyings)
    if not raw:
        return ["000300"] * n
    if len(raw) == 1:
        return raw * n
    if len(raw) == n:
        return raw
    provider_errors.append(
        f"index_code 项数 ({len(raw)}) 与标的数 ({n}) 不一致，已截断或末项填充"
    )
    if len(raw) < n:
        padded = list(raw)
        last = padded[-1]
        while len(padded) < n:
            padded.append(last)
        return padded
    return raw[:n]


def _pick_primary_fused(
    fused_by_symbol: Dict[str, FusionResult],
    underlyings: List[str],
) -> Optional[FusionResult]:
    if not fused_by_symbol:
        return None
    for sym in underlyings:
        if sym in fused_by_symbol:
            return fused_by_symbol[sym]
    first = sorted(fused_by_symbol.keys())[0]
    return fused_by_symbol[first]


def _resolve_dynamic_weights(strategy_ids: List[str]) -> Optional[Dict[str, float]]:
    try:
        from analysis.strategy_weight_manager import get_strategy_weights

        r = get_strategy_weights(strategies=strategy_ids)
        if isinstance(r, dict) and r.get("success") and isinstance(r.get("data"), dict):
            return {str(k): float(v) for k, v in r["data"].items() if isinstance(v, (int, float))}
    except Exception:
        pass
    return None


def tool_strategy_engine(
    underlying: str = "510300",
    index_code: str = "000300",
    mode: str = "production",
    use_dynamic_weights: bool = True,
    write_journal: bool = True,
    config_path: Optional[str] = None,
    sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    运行策略引擎：收集 SignalCandidate -> 融合 -> 可选写 Journal。

    Args:
        underlying: ETF 标的；多标的时用英文逗号分隔，如 ``510300,510500``
        index_code: 指数代码（趋势策略用）；单个则复用于所有标的，或与 underlying 同序逗号分隔列表
        mode: 传给 src 信号生成
        use_dynamic_weights: 是否合并动态权重（优先读 data 落盘，其次 get_strategy_weights）
        write_journal: 是否追加 strategy_fusion 到 trading_journal
        config_path: 可选自定义 yaml 路径
    """
    provider_errors: List[str] = []
    cfg = load_fusion_config(Path(config_path) if config_path else None)
    version = str(cfg.get("version", "1.0"))
    policy_root = cfg.get("policy") or {}
    policy = {
        "score_threshold": float(policy_root.get("score_threshold", 0.2)),
        "agree_ratio_min": float(policy_root.get("agree_ratio_min", 0.6)),
        "strong_abs_score": float(policy_root.get("strong_abs_score", 0.65)),
    }
    yaml_weights = dict(cfg.get("strategy_weights") or {})
    prov = cfg.get("providers") or {}

    requested_sources = {str(s).strip() for s in (sources or []) if str(s).strip()}
    if requested_sources:
        source_enabled = lambda name: name in requested_sources  # noqa: E731
    else:
        source_enabled = lambda name: bool(prov.get(name, False) if name == "llm" else prov.get(name, True))  # noqa: E731

    providers_used: List[str] = []
    for name in ("src_signal_generation", "etf_trend_following", "internal_chart_alert", "llm"):
        if source_enabled(name):
            providers_used.append(name)

    underlyings = _underlyings_list(underlying)
    index_codes = _align_index_codes(underlyings, index_code, provider_errors)

    inputs_parts = {
        "engine_inputs_hash_schema": "1",
        "policy_version": version,
        "fusion_policy": _fusion_policy_for_hash(policy),
        "strategy_weights_yaml": _strategy_weights_for_hash(yaml_weights),
        "underlyings": underlyings,
        "index_codes": index_codes,
        "mode": mode,
        "providers": providers_used,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    inputs_hash = _run_inputs_hash(inputs_parts)

    candidates: List[SignalCandidate] = []

    if source_enabled("src_signal_generation"):
        for sym in underlyings:
            try:
                candidates.extend(collect_from_src_signal_generation(sym, inputs_hash, mode=mode))
            except Exception as e:
                provider_errors.append(f"src_signal_generation[{sym}]: {e}")

    if source_enabled("etf_trend_following"):
        for sym, idx in zip(underlyings, index_codes):
            try:
                candidates.extend(collect_from_trend_following(sym, idx, inputs_hash))
            except Exception as e:
                provider_errors.append(f"etf_trend_following[{sym},{idx}]: {e}")

    if source_enabled("internal_chart_alert"):
        for sym in underlyings:
            try:
                candidates.extend(collect_from_internal_chart_alert(sym, inputs_hash))
            except Exception as e:
                provider_errors.append(f"internal_chart_alert[{sym}]: {e}")

    if source_enabled("llm"):
        try:
            candidates.extend(
                generate_llm_candidates(
                    {
                        "underlying": underlying,
                        "underlyings": underlyings,
                        "index_code": index_code,
                        "index_codes": index_codes,
                        "inputs_hash": inputs_hash,
                        "providers_llm": True,
                    }
                )
            )
        except Exception as e:
            provider_errors.append(f"llm: {e}")

    weights = merge_weights(yaml_weights, _resolve_dynamic_weights(list(yaml_weights.keys())) if use_dynamic_weights else None)

    oc = _load_openclaw_strategy_engine_config()
    evo = (oc.get("evolution") or {}) if oc.get("enabled", True) else {}
    if evo.get("persist_effective_weights") and weights:
        try:
            rel = str(evo.get("effective_weights_path", "data/strategy_fusion_effective_weights.json"))
            _persist_effective_weights(weights, rel)
        except Exception:
            pass

    fused_by_symbol = fuse_all_by_symbol(candidates, weights, policy)
    fused = _pick_primary_fused(fused_by_symbol, underlyings)
    summary = _build_fusion_summary(candidates, fused_by_symbol, policy["strong_abs_score"])
    contribution_raw: Dict[str, float] = {}
    for c in candidates:
        contribution_raw[c.strategy_id] = contribution_raw.get(c.strategy_id, 0.0) + abs(float(c.score)) * max(float(c.confidence), 0.0)
    contribution_sum = sum(contribution_raw.values())
    if contribution_sum > 0:
        source_contribution = {k: round(v / contribution_sum, 4) for k, v in sorted(contribution_raw.items())}
    else:
        source_contribution = {k: 0.0 for k in sorted(contribution_raw)}

    data_out: Dict[str, Any] = {
        "candidates": [c.to_dict() for c in candidates],
        "fused": fused.to_dict() if fused else None,
        "fused_by_symbol": {k: v.to_dict() for k, v in sorted(fused_by_symbol.items())},
        "summary": summary,
        "underlyings": underlyings,
        "index_codes": index_codes,
        "weights_effective": weights,
        "policy_version": version,
        "inputs_hash": inputs_hash,
        "provider_errors": provider_errors,
        "policy_applied": policy,
        "source_contribution": source_contribution,
    }

    if write_journal and fused_by_symbol:
        try:
            from src.trading_journal import append_journal_event

            base = Path(__file__).resolve().parents[2]
            append_journal_event(
                "strategy_fusion",
                {
                    "policy_version": version,
                    "weights_effective": weights,
                    "inputs_hash": inputs_hash,
                    "fused": fused.to_dict() if fused else None,
                    "fused_by_symbol": {k: v.to_dict() for k, v in sorted(fused_by_symbol.items())},
                    "candidate_count": len(candidates),
                    "underlying": underlying,
                    "underlyings": underlyings,
                    "index_code": index_code,
                    "index_codes": index_codes,
                    "summary": summary,
                },
                actor="tool_strategy_engine",
                base_dir=base,
            )
        except Exception:
            pass

    msg = "策略融合完成"
    if fused_by_symbol:
        if len(fused_by_symbol) == 1 and fused:
            msg = f"融合: {fused.direction} score={fused.score:.3f} conf={fused.confidence:.2f}"
        elif fused:
            msg = (
                f"{len(fused_by_symbol)} 标的已融合；主标的 {fused.symbol}: "
                f"{fused.direction} score={fused.score:.3f} conf={fused.confidence:.2f}"
            )
        else:
            msg = f"{len(fused_by_symbol)} 标的已融合"
    elif not candidates:
        msg = "无候选信号"
    else:
        msg = "融合未产出结果"

    return {
        "success": True,
        "message": msg,
        "data": data_out,
    }
