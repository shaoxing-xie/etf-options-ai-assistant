#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    td = _today()
    src = _read(ROOT / "data" / "semantic" / "rotation_latest" / f"{td}.json")
    data = src.get("data") if isinstance(src.get("data"), dict) else {}
    meta = src.get("_meta") if isinstance(src.get("_meta"), dict) else {}
    if not data:
        print(json.dumps({"success": False, "message": "rotation_latest missing", "trade_date": td}, ensure_ascii=False))
        return 1
    heatmap = {
        "_meta": {
            "schema_name": "semantic_rotation_heatmap_v1",
            "schema_version": "1.0.0",
            "task_id": meta.get("task_id", "etf-rotation-research"),
            "run_id": meta.get("run_id", ""),
            "data_layer": "L4",
            "generated_at": datetime.now().isoformat(),
            "trade_date": td,
            "quality_status": (data.get("data_quality") or {}).get("quality_status", "degraded"),
            "lineage_refs": [str(ROOT / "data" / "semantic" / "rotation_latest" / f"{td}.json")],
        },
        "data": {
            "trade_date": td,
            "heatmap": data.get("heatmap", []),
            "top5": data.get("top5", []),
            "environment": data.get("environment", {}),
            "explanations": data.get("data_quality", {}),
        },
    }
    share_dash = {
        "_meta": {
            "schema_name": "semantic_etf_share_dashboard_v1",
            "schema_version": "1.0.0",
            "task_id": meta.get("task_id", "etf-rotation-research"),
            "run_id": meta.get("run_id", ""),
            "data_layer": "L4",
            "generated_at": datetime.now().isoformat(),
            "trade_date": td,
            "quality_status": (data.get("data_quality") or {}).get("quality_status", "degraded"),
            "lineage_refs": [str(ROOT / "data" / "semantic" / "rotation_latest" / f"{td}.json")],
        },
        "data": {
            "trade_date": td,
            "rows": [
                {
                    "etf_code": row.get("symbol"),
                    "trend_score": ((row.get("three_factor") or {}).get("capital_resonance_score")),
                    "divergence_flags": ["none"],
                    "interpretation": "derived from rotation latest",
                }
                for row in (data.get("top10") or [])
            ],
        },
    }
    _write(ROOT / "data" / "semantic" / "rotation_heatmap" / f"{td}.json", heatmap)
    _write(ROOT / "data" / "semantic" / "etf_share_dashboard" / f"{td}.json", share_dash)
    print(json.dumps({"success": True, "trade_date": td}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

