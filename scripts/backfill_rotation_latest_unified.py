#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _dump_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _effective_gate(data: dict[str, Any]) -> str:
    eff = data.get("sector_environment_effective")
    if isinstance(eff, dict) and str(eff.get("effective_gate") or "").strip():
        return str(eff.get("effective_gate"))
    sec = data.get("sector_environment")
    if isinstance(sec, dict) and str(sec.get("gate") or "").strip():
        return str(sec.get("gate"))
    gate = (data.get("three_factor_context") or {}).get("gate") if isinstance(data.get("three_factor_context"), dict) else {}
    if isinstance(gate, dict):
        if gate.get("label"):
            return str(gate.get("label"))
        if gate.get("stage"):
            return str(gate.get("stage"))
    return "UNKNOWN"


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill unified_next_day / legacy_views for existing rotation_latest snapshot")
    ap.add_argument("--trade-date", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    path = root / "data" / "semantic" / "rotation_latest" / f"{args.trade_date}.json"
    payload = _load_json(path)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    if not data:
        print(json.dumps({"success": False, "message": "rotation_latest_missing_or_invalid", "path": str(path)}, ensure_ascii=False))
        return 1

    name_map = _load_json(root / "config" / "etf_name_map.json")
    top5 = data.get("top5") if isinstance(data.get("top5"), list) else []
    top10 = data.get("top10") if isinstance(data.get("top10"), list) else []
    recs = data.get("recommendations") if isinstance(data.get("recommendations"), list) else []

    by_symbol: dict[str, dict[str, Any]] = {}
    for row in top10:
        if isinstance(row, dict):
            sym = str(row.get("symbol") or "").strip()
            if sym and sym not in by_symbol:
                by_symbol[sym] = row

    gate = _effective_gate(data)
    unified: list[dict[str, Any]] = []
    if recs:
        seen_codes: set[str] = set()
        for rec in recs:
            if not isinstance(rec, dict):
                continue
            code = str(rec.get("etf_code") or rec.get("symbol") or "").strip()
            if code:
                seen_codes.add(code)
            joined = by_symbol.get(code)
            tf = (joined or {}).get("three_factor") if isinstance((joined or {}).get("three_factor"), dict) else {}
            sig = rec.get("signals") if isinstance(rec.get("signals"), dict) else {}
            unified.append(
                {
                    "rank": rec.get("rank"),
                    "etf_code": code,
                    "etf_name": rec.get("etf_name") or name_map.get(code) or "",
                    "sector": rec.get("sector") or "",
                    "unified_score": rec.get("composite_score") or rec.get("score"),
                    "components": {
                        "rps_20d": sig.get("rps_20d"),
                        "rps_5d": sig.get("rps_5d"),
                        "rps_change": sig.get("rps_change"),
                        "three_factor_score": (joined or {}).get("score") if isinstance(joined, dict) else None,
                        "volume_ratio": sig.get("volume_ratio"),
                        "volume_status": sig.get("volume_status"),
                    },
                    "cautions": rec.get("cautions") if isinstance(rec.get("cautions"), list) else [],
                    "explain_bullets": rec.get("explain_bullets") if isinstance(rec.get("explain_bullets"), list) else [],
                    "allocation_pct": rec.get("allocation_pct"),
                    "gate_effective": gate,
                    "three_factor_missing": joined is None,
                    "three_factor_breakdown": {
                        "momentum_score": tf.get("momentum_score"),
                        "capital_resonance_score": tf.get("capital_resonance_score"),
                        "environment_gate": tf.get("environment_gate"),
                    },
                }
            )
        # supplement with three-factor rows not in RPS recommendations
        rank_base = len(unified)
        for row in top10:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            if not sym or sym in seen_codes:
                continue
            tf = row.get("three_factor") if isinstance(row.get("three_factor"), dict) else {}
            rank_base += 1
            unified.append(
                {
                    "rank": rank_base,
                    "etf_code": sym,
                    "etf_name": row.get("name") or name_map.get(sym) or "",
                    "sector": row.get("pool_type") or "",
                    "unified_score": row.get("score") or row.get("composite_score"),
                    "components": {
                        "rps_20d": None,
                        "rps_5d": None,
                        "rps_change": None,
                        "three_factor_score": row.get("score"),
                        "volume_ratio": None,
                        "volume_status": None,
                    },
                    "cautions": ["from_three_factor_only"],
                    "explain_bullets": ["三维补充：该标的未进入当日RPS TopK，按三维共振评分补充展示。"],
                    "allocation_pct": None,
                    "gate_effective": gate,
                    "three_factor_missing": False,
                    "three_factor_breakdown": {
                        "momentum_score": tf.get("momentum_score"),
                        "capital_resonance_score": tf.get("capital_resonance_score"),
                        "environment_gate": tf.get("environment_gate"),
                    },
                }
            )
            seen_codes.add(sym)
            if len(unified) >= 10:
                break
    else:
        for i, row in enumerate(top5):
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            tf = row.get("three_factor") if isinstance(row.get("three_factor"), dict) else {}
            unified.append(
                {
                    "rank": i + 1,
                    "etf_code": sym,
                    "etf_name": row.get("name") or name_map.get(sym) or "",
                    "sector": row.get("pool_type") or "",
                    "unified_score": row.get("score") or row.get("composite_score"),
                    "components": {
                        "rps_20d": None,
                        "rps_5d": None,
                        "rps_change": None,
                        "three_factor_score": row.get("score"),
                        "volume_ratio": None,
                        "volume_status": None,
                    },
                    "cautions": ["sector_rotation_recommendations_empty"],
                    "explain_bullets": [],
                    "allocation_pct": None,
                    "gate_effective": gate,
                    "three_factor_missing": False,
                    "three_factor_breakdown": {
                        "momentum_score": tf.get("momentum_score"),
                        "capital_resonance_score": tf.get("capital_resonance_score"),
                        "environment_gate": tf.get("environment_gate"),
                    },
                }
            )

    data["unified_next_day"] = unified
    data["legacy_views"] = {
        "three_factor_top5": top5,
        "three_factor_top10": top10,
        "rps_recommendations": recs,
    }
    if "sector_environment_effective" not in data:
        data["sector_environment_effective"] = {
            "effective_gate": gate,
            "sector_rotation_environment": data.get("sector_environment") if isinstance(data.get("sector_environment"), dict) else {},
            "three_factor_gate": (data.get("three_factor_context") or {}).get("gate")
            if isinstance(data.get("three_factor_context"), dict)
            else {},
            "sentiment": (data.get("three_factor_context") or {}).get("sentiment")
            if isinstance(data.get("three_factor_context"), dict)
            else {},
        }
    dq = data.get("data_quality") if isinstance(data.get("data_quality"), dict) else {}
    if "structured_warnings" not in dq:
        dq["structured_warnings"] = []
    data["data_quality"] = dq

    payload["data"] = data
    meta["schema_version"] = "1.1.0"
    payload["_meta"] = meta
    _dump_json(path, payload)
    print(json.dumps({"success": True, "path": str(path), "unified_rows": len(unified)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
