#!/usr/bin/env python3
"""
计划 §4.6b：≥30 个交易日回放 `build_intraday_guide`，汇总信号分布并写入门槛文件。

读取 data/semantic/nasdaq_513300_monitor_events/*.jsonl（完整 report_data 行），
无需实时行情。粗 KPI：monitor_point×signal 计数、相邻事件信号翻转率。

用法：
  /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/replay_intraday_guide_513300.py --days 45

产出：
  data/meta/intraday_guide_replay_gate.json（passes_gate 供 nasdaq_intraday_guide 判定 production/experimental）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45, help="扫描最近 N 个交易日的 jsonl 文件")
    ap.add_argument("--min-events", type=int, default=30, help="门槛：最少评估事件条数")
    ap.add_argument("--max-flip-rate", type=float, default=0.62, help="门槛：相邻信号翻转率上限（启发式）")
    args = ap.parse_args()

    from plugins.analysis.nasdaq_intraday_guide import build_intraday_guide

    base = ROOT / "data" / "semantic" / "nasdaq_513300_monitor_events"
    if not base.is_dir():
        print(json.dumps({"success": False, "message": "missing_monitor_events_dir"}, ensure_ascii=False))
        return 1

    all_files = sorted([p for p in base.glob("*.jsonl") if p.is_file()], key=lambda x: x.stem)
    n_files = max(1, min(int(args.days), 400))
    files = all_files[-n_files:] if len(all_files) > n_files else all_files

    events_out: List[Dict[str, Any]] = []
    mp_sig: Counter = Counter()
    seq_pairs: List[Tuple[str, str]] = []
    prev_sig = ""

    for fp in files:
        rows = _read_jsonl(fp)
        for rd in rows:
            if str(rd.get("market_profile") or "") != "nasdaq_513300":
                continue
            mc = rd.get("monitor_context") if isinstance(rd.get("monitor_context"), dict) else {}
            mp = str(mc.get("monitor_point") or "").strip().upper()
            if mp not in {"M1", "M2", "M3", "M4", "M5", "M6", "M7"}:
                continue
            try:
                ig = build_intraday_guide(rd)
            except Exception as e:
                events_out.append({"trade_date": fp.stem, "monitor_point": mp, "error": str(e)})
                continue
            sig = str(ig.get("signal") or "").strip().upper()
            mp_sig[(mp, sig)] += 1
            if prev_sig and sig != prev_sig:
                seq_pairs.append((prev_sig, sig))
            prev_sig = sig
            events_out.append({"trade_date": fp.stem, "monitor_point": mp, "signal": sig, "weight": ig.get("weight")})

    flip_n = sum(1 for a, b in seq_pairs if a != b)
    flip_rate = (flip_n / float(len(seq_pairs))) if seq_pairs else 0.0
    n_ev = len(events_out)
    passes = n_ev >= int(args.min_events) and flip_rate <= float(args.max_flip_rate)

    gate_path = ROOT / "data" / "meta" / "intraday_guide_replay_gate.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "events_evaluated": n_ev,
        "files_scanned": len(files),
        "min_events_required": int(args.min_events),
        "max_flip_rate_threshold": float(args.max_flip_rate),
        "metrics": {
            "signal_by_monitor_point": {f"{a}|{b}": int(mp_sig[(a, b)]) for a, b in sorted(mp_sig.keys())},
            "adjacent_pairs_n": len(seq_pairs),
            "flip_rate": round(flip_rate, 4),
        },
        "passes_gate": passes,
    }
    gate_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"success": True, "gate_path": str(gate_path), "summary": payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
