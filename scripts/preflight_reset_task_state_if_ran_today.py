#!/usr/bin/env python3
"""
同日已成功完成的编排 state 预检清理（仅 data/state/<task_id>.json）。

用于「每日一次」类任务在 cron 再次触发时仍能 claim_execution，而无需删 L2/L4 落盘。
典型任务：`intraday-tail-screening`（`--trigger-window intraday-30m`）、`nightly-stock-screening`（`--trigger-window daily`）。
尾盘 shell 用 `ORCH_TAIL_PREFLIGHT_RESET_SAME_DAY=0` 关闭；夜盘用 `ORCH_NIGHTLY_PREFLIGHT_RESET_SAME_DAY=0` 关闭。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_DEFAULT_ROOT = Path(__file__).resolve().parents[1]

_TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$", re.I)


def _default_trade_date() -> str:
    try:
        return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def _load_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        o = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return o if isinstance(o, dict) else {}


def should_remove_state(
    state: dict[str, object],
    *,
    trade_date: str,
    trigger_window: str,
) -> tuple[bool, str]:
    if state.get("state") != "succeeded":
        return False, "state_not_succeeded"
    if str(state.get("trade_date") or "").strip() != trade_date:
        return False, "trade_date_mismatch"
    tw = str(state.get("trigger_window") or "").strip()
    if tw and tw != trigger_window:
        return False, "trigger_window_mismatch"
    return True, "same_day_succeeded"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=None, help="仓库根（单测用；默认脚本上级目录）")
    ap.add_argument("--task-id", default="intraday-tail-screening")
    ap.add_argument("--trade-date", default="", help="默认：Asia/Shanghai 当日")
    ap.add_argument("--trigger-window", default="intraday-30m")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root is not None else _DEFAULT_ROOT

    task_id = str(args.task_id or "").strip()
    if not task_id or not _TASK_ID_RE.match(task_id):
        print(json.dumps({"success": False, "message": "invalid_task_id"}, ensure_ascii=False))
        return 2

    trade_date = (str(args.trade_date or "").strip() or _default_trade_date()).strip()
    trigger_window = str(args.trigger_window or "intraday-30m").strip()

    state_path = root / "data" / "state" / f"{task_id}.json"
    state = _load_state(state_path)
    if not state:
        print(json.dumps({"success": True, "action": "noop", "reason": "no_state_file"}, ensure_ascii=False))
        return 0

    ok, reason = should_remove_state(state, trade_date=trade_date, trigger_window=trigger_window)
    if not ok:
        print(json.dumps({"success": True, "action": "noop", "reason": reason}, ensure_ascii=False))
        return 0

    if args.dry_run:
        print(
            json.dumps(
                {"success": True, "action": "would_remove", "path": str(state_path), "reason": reason},
                ensure_ascii=False,
            )
        )
        return 0

    try:
        state_path.unlink()
    except OSError as e:
        print(json.dumps({"success": False, "message": str(e)}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "success": True,
                "action": "removed_state_file",
                "path": str(state_path),
                "task_id": task_id,
                "trade_date": trade_date,
                "reason": reason,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
