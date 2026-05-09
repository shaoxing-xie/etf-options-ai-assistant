#!/usr/bin/env python3
"""
滚动验收：读取 data/decision/nasdaq_513300_next_open_direction_events 最近若干交易日的 JSONL，
汇总方向标签（若有）、p_up、predictor_run_kind（来自 probability_debug 或 _meta）。
需已落盘的历史产物；无标签时仅输出分布统计。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read_jsonl_tail(path: Path, max_lines: int = 500) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    rows: List[Dict[str, Any]] = []
    for line in lines[-max_lines:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    base = ROOT / "data" / "decision" / "nasdaq_513300_next_open_direction_events"
    files = sorted(base.glob("*.jsonl"), reverse=True)[: max(1, int(args.days))]
    kinds: Dict[str, int] = {}
    n = 0
    for fp in files:
        for row in _read_jsonl_tail(fp, max_lines=400):
            n += 1
            dbg = row.get("probability_debug") if isinstance(row.get("probability_debug"), dict) else {}
            k = str(dbg.get("predictor_run_kind") or row.get("_meta", {}).get("predictor_run_kind") or "unknown")
            kinds[k] = kinds.get(k, 0) + 1
    summary = {"files_scanned": len(files), "rows": n, "predictor_run_kind_counts": kinds}
    print(json.dumps({"success": True, "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
