#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _top_symbols(rot_latest: Dict[str, Any], k: int) -> List[str]:
    data = rot_latest.get("data") if isinstance(rot_latest.get("data"), dict) else {}
    top10 = data.get("top10") if isinstance(data.get("top10"), list) else []
    out: List[str] = []
    for row in top10[:k]:
        if isinstance(row, dict):
            s = str(row.get("symbol") or "").strip()
            if s:
                out.append(s)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Minimal offline evaluation/ablation evidence for rotation outputs")
    p.add_argument("--trade-date", default=datetime.now().strftime("%Y-%m-%d"))
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--history-days", type=int, default=3, help="Use last N semantic rotation_latest snapshots if exist")
    args = p.parse_args()

    td = str(args.trade_date)
    k = max(1, min(int(args.top_k), 20))
    n_hist = max(1, min(int(args.history_days), 20))

    # Use semantic outputs as single source of truth for evaluation evidence.
    latest_path = ROOT / "data" / "semantic" / "rotation_latest" / f"{td}.json"
    rot = _load_json(latest_path)

    # rank stability (topK overlap) across last n_hist trade_dates if present
    # We simply walk backwards over available files by mtime in the same folder.
    folder = ROOT / "data" / "semantic" / "rotation_latest"
    files = sorted(folder.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
    files = files[:n_hist]
    snaps: List[Dict[str, Any]] = []
    for fp in files:
        obj = _load_json(fp)
        meta = obj.get("_meta") if isinstance(obj.get("_meta"), dict) else {}
        snaps.append(
            {
                "trade_date": str(meta.get("trade_date") or fp.stem),
                "run_id": meta.get("run_id"),
                "quality_status": meta.get("quality_status"),
                "topk": _top_symbols(obj, k),
            }
        )

    overlaps: List[Dict[str, Any]] = []
    for i in range(1, len(snaps)):
        a = snaps[i - 1]["topk"]
        b = snaps[i]["topk"]
        inter = sorted(set(a) & set(b))
        overlaps.append(
            {
                "pair": f"{snaps[i-1]['trade_date']} vs {snaps[i]['trade_date']}",
                "topk_overlap": len(inter),
                "topk_turnover_rate": (1.0 - (len(inter) / float(k))) if k > 0 else None,
                "intersection": inter,
            }
        )

    evidence = {
        "trade_date": td,
        "inputs": {
            "rotation_latest_path": str(latest_path),
            "top_k": k,
            "history_days": n_hist,
        },
        "availability": {
            "rotation_latest_exists": bool(rot),
            "snapshots_used": len(snaps),
        },
        "rank_stability": {
            "snapshots": snaps,
            "pairwise_overlaps": overlaps,
        },
        "notes": [
            "This is a minimal reproducible evaluation evidence based on L4 semantic snapshots.",
            "Ablation across engines/weights requires deterministic offline price dataset; not executed here.",
        ],
    }

    out_path = ROOT / "data" / "meta" / "evidence" / f"rotation_ablation_{td}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "path": str(out_path), "evidence": evidence}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

