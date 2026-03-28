#!/usr/bin/env python3
"""
多模型区间预测 — 离线融合试验（契约见 docs/research/prediction_fusion_contract.md）。

示例（先在仓库根 cd，或用绝对路径调用脚本）：
  cd /path/to/etf-options-ai-assistant
  echo '[{"source":"a","symbol":"510300","upper":4.8,"lower":4.6,"weight":1}]' | \\
    python scripts/prediction_fusion_experiment.py --stdin

  python scripts/prediction_fusion_experiment.py --file predictions_bundle.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


def _midpoint(p: Dict[str, Any]) -> float:
    u = float(p["upper"])
    l = float(p["lower"])
    return (u + l) / 2.0


def _filter_zscore(rows: List[Dict[str, Any]], zmax: float) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if len(rows) < 3:
        return list(rows), []
    mids = [_midpoint(r) for r in rows]
    mean = sum(mids) / len(mids)
    var = sum((m - mean) ** 2 for m in mids) / max(len(mids) - 1, 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std <= 1e-12:
        return list(rows), []
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for r, m in zip(rows, mids):
        z = abs(m - mean) / std
        if z <= zmax:
            kept.append(r)
        else:
            dropped.append(r)
    return kept if kept else list(rows), dropped


def _weight(r: Dict[str, Any]) -> float:
    w = r.get("weight", 1.0)
    try:
        x = float(w)
        return max(0.0, x)
    except (TypeError, ValueError):
        return 1.0


def weighted_quantile(values: Sequence[float], weights: Sequence[float], q: float) -> float:
    """q in [0,1]；权重非负。"""
    if not values:
        return float("nan")
    pairs = sorted(zip(values, weights), key=lambda t: t[0])
    total = sum(w for _, w in pairs)
    if total <= 0:
        return float(sum(v for v, _ in pairs) / len(pairs))
    target = q * total
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= target:
            return v
    return pairs[-1][0]


def fuse_predictions(rows: List[Dict[str, Any]], zmax: float = 2.0) -> Dict[str, Any]:
    kept, dropped = _filter_zscore(rows, zmax=zmax)
    lowers = [float(r["lower"]) for r in kept]
    uppers = [float(r["upper"]) for r in kept]
    ws = [_weight(r) for r in kept]
    if not kept:
        return {"error": "no predictions", "fused_lower": None, "fused_upper": None}

    fl = weighted_quantile(lowers, ws, 0.20)
    fu = weighted_quantile(uppers, ws, 0.80)
    if fl > fu:
        fl, fu = fu, fl

    return {
        "fused_lower": fl,
        "fused_upper": fu,
        "sources_used": [r.get("source", "?") for r in kept],
        "dropped_sources": [r.get("source", "?") for r in dropped],
        "n_in": len(rows),
        "n_kept": len(kept),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline prediction interval fusion experiment")
    parser.add_argument("--file", type=str, help="JSON file: array of prediction objects")
    parser.add_argument("--stdin", action="store_true", help="Read JSON array from stdin")
    parser.add_argument("--zmax", type=float, default=2.0, help="Midpoint z-score cutoff")
    args = parser.parse_args()

    if args.stdin:
        raw = sys.stdin.read()
    elif args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
    else:
        parser.error("Provide --file or --stdin")

    data = json.loads(raw)
    if not isinstance(data, list):
        raise SystemExit("JSON root must be an array")

    out = fuse_predictions(data, zmax=args.zmax)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
