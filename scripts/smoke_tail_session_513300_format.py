#!/usr/bin/env python3
"""
非交易日 / 离线格式烟测：依次生成 M1–M7 的 tail_session report_data（fetch_mode=test），
不写 webhook；用于校验模板字段完整性与 intraday_guide 挂钩。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from plugins.notification.run_tail_session_analysis import build_tail_session_report_data

    points = ["M1", "M2", "M3", "M4", "M5", "M6", "M7"]
    out_dir = ROOT / "data" / "cache" / "smoke_513300_format"
    out_dir.mkdir(parents=True, exist_ok=True)
    for mp in points:
        rd, errors = build_tail_session_report_data(
            fetch_mode="test",
            market_profile="nasdaq_513300",
            monitor_point=mp,
            monitor_bundle=None,
            workflow_profile="cron_balanced",
            stage_budget_profile="balanced",
            emit_stage_timing=False,
            max_concurrency=2,
        )
        payload = {
            "monitor_point": mp,
            "trade_date": rd.get("trade_date"),
            "report_type": rd.get("report_type"),
            "has_intraday_guide": bool((rd.get("analysis") or {}).get("intraday_guide")),
            "runner_errors": errors,
            "keys_analysis": sorted(list((rd.get("analysis") or {}).keys()))[:40],
        }
        (out_dir / f"summary_{mp}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps({"success": True, "written_under": str(out_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
