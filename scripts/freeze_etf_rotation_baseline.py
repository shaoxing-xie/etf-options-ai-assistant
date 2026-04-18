#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _extract_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else {}
    data = data if isinstance(data, dict) else {}
    ranked = data.get("ranked") if isinstance(data.get("ranked"), list) else []
    top10 = []
    for row in ranked[:10]:
        if not isinstance(row, dict):
            continue
        top10.append(
            {
                "symbol": row.get("symbol"),
                "name": row.get("name"),
                "score": row.get("score"),
                "pool": row.get("pool"),
            }
        )
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "success": bool(payload.get("success")) if isinstance(payload, dict) else False,
        "message": payload.get("message") if isinstance(payload, dict) else "",
        "indicator_runtime": data.get("indicator_runtime"),
        "shadow_compare": data.get("shadow_compare"),
        "top10": top10,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze etf_rotation_research baseline snapshot")
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--mode", default="test", choices=["test", "prod"])
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="Use ~/.openclaw/memory/etf_rotation_last_report_<today>.json snapshot instead of running tool",
    )
    parser.add_argument(
        "--output",
        default="artifacts/indicator-migration/etf_rotation_baseline.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    st = time.perf_counter()
    if args.from_cache:
        today = datetime.now().strftime("%Y-%m-%d")
        cache_file = Path.home() / ".openclaw" / "memory" / f"etf_rotation_last_report_{today}.json"
        if not cache_file.exists():
            raise FileNotFoundError(f"cache file not found: {cache_file}")
        report = json.loads(cache_file.read_text(encoding="utf-8"))
        report_data = report.get("report_data") if isinstance(report.get("report_data"), dict) else {}
        out = {
            "success": True,
            "message": "loaded from cache",
            "data": {
                "ranked": ((report_data.get("raw") or {}).get("ranked") if isinstance(report_data, dict) else []),
                "indicator_runtime": report_data.get("indicator_runtime"),
                "shadow_compare": report_data.get("shadow_compare"),
            },
        }
    else:
        payload = json.dumps(
            {"lookback_days": args.lookback_days, "top_k": args.top_k, "mode": args.mode},
            ensure_ascii=False,
        )
        proc = subprocess.run(
            [sys.executable, "tool_runner.py", "tool_etf_rotation_research", payload],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"tool_runner failed: {proc.stderr.strip() or proc.stdout.strip()}")
        out = json.loads(proc.stdout.strip())
    elapsed_ms = int((time.perf_counter() - st) * 1000)

    snapshot = _extract_snapshot(out if isinstance(out, dict) else {})
    snapshot["duration_ms"] = elapsed_ms
    snapshot["params"] = {
        "lookback_days": args.lookback_days,
        "top_k": args.top_k,
        "mode": args.mode,
    }

    op = Path(args.output)
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"baseline written: {op}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
