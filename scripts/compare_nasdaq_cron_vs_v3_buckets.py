#!/usr/bin/env python3
"""
Phase 6（计划）：量化「现网 cron :15/:45 触发时刻」与参考 v3 时点桶的一致性。

不修改 cron；仅打印对照表，供决定是否调 jobs.json / _resolve_monitor_context。

说明：PROCESS 分支按当前 wall-clock 映射 M1–M6（见 run_tail_session_analysis._resolve_monitor_context）。
下列 v3 参考时点为计划文档中的示意锚点，可通过本脚本输出与现网映射对照。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Dict, List

try:
    import pytz
except ImportError:
    pytz = None  # type: ignore


def _resolve_mp_process(hhmm: str) -> str:
    """与 run_tail_session_analysis._resolve_monitor_context(PROCESS) 逻辑一致。"""
    if "09:00" <= hhmm < "09:30":
        return "M1"
    if "09:30" <= hhmm < "10:00":
        return "M2"
    if "10:00" <= hhmm < "10:30":
        return "M3"
    if "10:30" <= hhmm < "11:30":
        return "M4"
    if "13:00" <= hhmm < "13:30":
        return "M5"
    if "13:30" <= hhmm < "14:30":
        return "M6"
    return "M7"


# 参考「v3 标准步骤」锚点（示意；若与贵司 v3 表不一致请改此字典后重跑脚本）
V3_REFERENCE_MP: Dict[str, str] = {
    "09:30": "M1",
    "10:00": "M2",
    "10:15": "M3",
    "11:30": "M4",
    "13:15": "M5",
    "14:00": "M6",
}


def main() -> int:
    # 与 OpenClaw cron `15,45 9-10,13 * * 1-5` 对齐的触发时刻（上海）
    cron_times: List[str] = ["09:15", "09:45", "10:15", "10:45", "13:15", "13:45"]
    rows: List[Dict[str, str]] = []
    mismatches = 0
    for ct in cron_times:
        mp_proc = _resolve_mp_process(ct)
        v3_mp = V3_REFERENCE_MP.get(ct, "")
        match = "n/a" if not v3_mp else ("yes" if v3_mp == mp_proc else "no")
        if match == "no":
            mismatches += 1
        rows.append(
            {
                "cron_trigger_shanghai": ct,
                "process_mapped_mp": mp_proc,
                "v3_reference_mp": v3_mp or "(未配置该触发点)",
                "match": match,
            }
        )

    tz_note = "Asia/Shanghai"
    if pytz:
        tz_note = str(datetime.now(pytz.timezone("Asia/Shanghai")).tzinfo)

    out = {
        "success": True,
        "timezone": tz_note,
        "v3_reference_note": "V3_REFERENCE_MP 仅为脚本内可编辑锚点，用于一致性对照而非行情计算。",
        "cron_triggers": rows,
        "mismatch_count_vs_configured_v3": mismatches,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
