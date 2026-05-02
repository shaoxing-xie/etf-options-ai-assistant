#!/usr/bin/env python3
"""
固定日期回放：2026-04-30(轮动基准) -> 2026-05-01(报告日, 非交易日夜间)。

用途：
- 端到端验证 tool_run_opening_analysis_and_send 的开盘实盘报告链路
- 避免依赖当前系统时钟，稳定复现“前日研究 + 当日验证”口径

默认 test 模式（不真实发送）；可加 --prod 触发真实发送。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    parser = argparse.ArgumentParser(description="Replay opening rotation report with fixed dates.")
    parser.add_argument("--prod", action="store_true", help="Use mode=prod for real delivery.")
    args = parser.parse_args()

    from plugins.notification.run_opening_analysis import tool_run_opening_analysis_and_send

    fixed_now = datetime(2026, 5, 1, 21, 20, 0)
    mode = "prod" if args.prod else "test"

    with patch(
        "plugins.notification.run_opening_analysis._now_sh",
        return_value=fixed_now,
    ), patch(
        "plugins.notification.run_opening_analysis._previous_trading_day_ymd",
        return_value="2026-04-30",
    ):
        out = tool_run_opening_analysis_and_send(
            mode=mode,
            fetch_mode="test",
            report_variant="realtime",
            workflow_profile="cron_balanced",
        )

    data = out.get("data") if isinstance(out, dict) and isinstance(out.get("data"), dict) else {}
    payload = {
        "success": bool(out.get("success")) if isinstance(out, dict) else False,
        "mode": mode,
        "run_quality": data.get("run_quality"),
        "report_type": data.get("report_type"),
        "analysis_health": data.get("analysis_health"),
        "delivery": data.get("delivery"),
        "runner_errors_count": len(data.get("runner_errors") or []) if isinstance(data.get("runner_errors"), list) else 0,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

