#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def main() -> int:
    td = datetime.now().strftime("%Y-%m-%d")
    rot = _load_json(ROOT / "data" / "semantic" / "rotation_latest" / f"{td}.json")
    heat = _load_json(ROOT / "data" / "semantic" / "rotation_heatmap" / f"{td}.json")
    share = _load_json(ROOT / "data" / "semantic" / "etf_share_dashboard" / f"{td}.json")
    quality = {
        "trade_date": td,
        "datasets_ready": {
            "rotation_latest": bool(rot),
            "rotation_heatmap": bool(heat),
            "etf_share_dashboard": bool(share),
        },
        "kpis": {
            "top5_count": len((((rot.get("data") if isinstance(rot.get("data"), dict) else {}) or {}).get("top5") or [])),
            "heatmap_rows": len((((heat.get("data") if isinstance(heat.get("data"), dict) else {}) or {}).get("heatmap") or [])),
            "share_rows": len((((share.get("data") if isinstance(share.get("data"), dict) else {}) or {}).get("rows") or [])),
        },
    }
    out_path = ROOT / "data" / "meta" / "evidence" / f"rotation_quality_{td}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "path": str(out_path), "quality": quality}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

