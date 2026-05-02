#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _assess_gate_from_recs(recs: list[dict[str, Any]]) -> tuple[str, float, list[str], str]:
    vals: list[float] = []
    for r in recs:
        sig = r.get("signals") if isinstance(r.get("signals"), dict) else {}
        try:
            v = float(sig.get("rps_20d"))
        except Exception:
            continue
        vals.append(v)
    if not vals:
        return "UNKNOWN", 1.0, ["env_rps_unavailable_in_snapshot"], "快照中无可用 RPS(20d)，无法修复插件环境门闸。"
    n = len(vals)
    strong_ratio = sum(1 for x in vals if x >= 85.0) / float(n)
    if strong_ratio > 0.30:
        return "GO", 1.0, ["env_gate_backfilled_go"], "由快照回填门闸：市场结构偏强。"
    if strong_ratio > 0.10:
        return "CAUTION", 0.5, ["env_gate_backfilled_caution"], "由快照回填门闸：建议降仓。"
    return "STOP", 0.0, ["env_gate_backfilled_stop"], "由快照回填门闸：建议暂停轮动。"


def main() -> int:
    ap = argparse.ArgumentParser(description="Fix UNKNOWN sector gate in rotation_latest snapshot.")
    ap.add_argument("--trade-date", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    p = root / "data" / "semantic" / "rotation_latest" / f"{args.trade_date}.json"
    obj = _read(p)
    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
    if not data:
        print(json.dumps({"success": False, "message": "rotation_latest_invalid", "path": str(p)}, ensure_ascii=False))
        return 1
    recs = data.get("recommendations") if isinstance(data.get("recommendations"), list) else []
    sec_env = data.get("sector_environment") if isinstance(data.get("sector_environment"), dict) else {}

    gate = str(sec_env.get("gate") or "")
    if gate and gate != "UNKNOWN":
        print(json.dumps({"success": True, "message": "already_not_unknown", "gate": gate}, ensure_ascii=False))
        return 0

    new_gate, mult, reason_codes, note = _assess_gate_from_recs([x for x in recs if isinstance(x, dict)])
    sec_env["gate"] = new_gate
    sec_env["allocation_multiplier"] = mult
    sec_env["reason_codes"] = reason_codes
    sec_env["human_notes"] = note
    data["sector_environment"] = sec_env
    eff = data.get("sector_environment_effective") if isinstance(data.get("sector_environment_effective"), dict) else {}
    eff["effective_gate"] = new_gate
    eff["sector_rotation_environment"] = sec_env
    data["sector_environment_effective"] = eff
    obj["data"] = data
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "gate": new_gate, "path": str(p)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
