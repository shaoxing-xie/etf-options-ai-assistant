#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.chart_console.api.services import ApiServices


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--trade-date", default="")
    p.add_argument("--window", type=int, default=5)
    args = p.parse_args()

    svc = ApiServices()
    metrics = svc.get_semantic_research_metrics(args.trade_date, args.window)
    diagnostics = svc.get_semantic_research_diagnostics(args.trade_date, args.window)
    assert metrics.get("success") is True
    assert diagnostics.get("success") is True
    data = metrics.get("data") or {}
    assert isinstance(data.get("_meta"), dict)
    assert data["_meta"].get("schema_name") == "research_metrics_v1"
    out = {
        "research_metrics_meta": data.get("_meta"),
        "research_diagnostics_meta": (diagnostics.get("data") or {}).get("_meta"),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
        raise
