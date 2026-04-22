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
    args = p.parse_args()
    svc = ApiServices()
    factor = svc.get_semantic_factor_diagnostics(args.trade_date, period="week")
    attr = svc.get_semantic_strategy_attribution(args.trade_date)
    assert factor.get("success") is True
    assert attr.get("success") is True
    fd = factor.get("data") or {}
    at = attr.get("data") or {}
    assert (fd.get("_meta") or {}).get("schema_name") == "factor_diagnostics_v1"
    assert (at.get("_meta") or {}).get("schema_name") == "strategy_attribution_v1"
    print(
        json.dumps(
            {
                "factor_meta": fd.get("_meta"),
                "attribution_meta": at.get("_meta"),
                "factor_count": len(fd.get("factors") or []),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
