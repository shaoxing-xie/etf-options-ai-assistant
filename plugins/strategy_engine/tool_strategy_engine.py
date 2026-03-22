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

from strategy_engine.fusion import fuse_all, load_fusion_config, merge_weights
from strategy_engine.llm_strategy import generate_llm_candidates
from strategy_engine.rule_adapters import collect_from_src_signal_generation, collect_from_trend_following
from strategy_engine.schemas import SignalCandidate


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
) -> Dict[str, Any]:
    """
    运行策略引擎：收集 SignalCandidate -> 融合 -> 可选写 Journal。

    Args:
        underlying: ETF 标的
        index_code: 指数代码（趋势策略用）
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

    providers_used: List[str] = []
    if prov.get("src_signal_generation", True):
        providers_used.append("src_signal_generation")
    if prov.get("etf_trend_following", True):
        providers_used.append("etf_trend_following")
    if prov.get("llm", False):
        providers_used.append("llm")

    inputs_parts = {
        "underlying": underlying,
        "index_code": index_code,
        "mode": mode,
        "providers": providers_used,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    inputs_hash = _run_inputs_hash(inputs_parts)

    candidates: List[SignalCandidate] = []

    if prov.get("src_signal_generation", True):
        try:
            candidates.extend(collect_from_src_signal_generation(underlying, inputs_hash, mode=mode))
        except Exception as e:
            provider_errors.append(f"src_signal_generation: {e}")

    if prov.get("etf_trend_following", True):
        try:
            candidates.extend(collect_from_trend_following(underlying, index_code, inputs_hash))
        except Exception as e:
            provider_errors.append(f"etf_trend_following: {e}")

    if prov.get("llm", False):
        try:
            candidates.extend(
                generate_llm_candidates(
                    {"underlying": underlying, "index_code": index_code, "inputs_hash": inputs_hash}
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

    fused = fuse_all(candidates, weights, policy)

    data_out: Dict[str, Any] = {
        "candidates": [c.to_dict() for c in candidates],
        "fused": fused.to_dict() if fused else None,
        "weights_effective": weights,
        "policy_version": version,
        "inputs_hash": inputs_hash,
        "provider_errors": provider_errors,
        "policy_applied": policy,
    }

    if write_journal and fused:
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
                    "candidate_count": len(candidates),
                    "underlying": underlying,
                    "index_code": index_code,
                },
                actor="tool_strategy_engine",
                base_dir=base,
            )
        except Exception:
            pass

    msg = "策略融合完成"
    if fused:
        msg = f"融合: {fused.direction} score={fused.score:.3f} conf={fused.confidence:.2f}"
    elif not candidates:
        msg = "无候选信号"
    else:
        msg = "融合未产出结果"

    return {
        "success": True,
        "message": msg,
        "data": data_out,
    }
