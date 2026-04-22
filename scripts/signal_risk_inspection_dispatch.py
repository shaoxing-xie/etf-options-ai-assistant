from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


@dataclass(frozen=True)
class DispatchDecision:
    should_run: bool
    phase: str | None
    reason: str


def _parse_debug_now(raw: str | None) -> datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _now_sh(debug_now: str | None) -> datetime:
    dt = _parse_debug_now(debug_now)
    if dt is not None:
        return dt
    if ZoneInfo is None:
        return datetime.now()
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _decide(now_sh: datetime, *, force: bool) -> DispatchDecision:
    h = int(now_sh.hour)
    m = int(now_sh.minute)

    # Original schedules:
    # - morning: 15,45 9 * * 1-5
    # - midday:  15,45 10-11 * * 1-5
    # - afternoon: 0,30 13-14 * * 1-5
    if h == 9 and m in (15, 45):
        return DispatchDecision(True, "morning", "matched schedule: morning")
    if h in (10, 11) and m in (15, 45):
        return DispatchDecision(True, "midday", "matched schedule: midday")
    if h in (13, 14) and m in (0, 30):
        return DispatchDecision(True, "afternoon", "matched schedule: afternoon")
    if force:
        # Default force phase: pick the closest semantic segment by hour.
        if h <= 9:
            phase = "morning"
        elif h <= 12:
            phase = "midday"
        else:
            phase = "afternoon"
        return DispatchDecision(True, phase, "force run")
    return DispatchDecision(False, None, "outside schedule window")


def _print(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def main() -> int:
    # Ensure repo root is importable when invoked via absolute script path.
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="prod", choices=["prod", "test"])
    p.add_argument("--fetch-mode", default="production", choices=["production", "test"])
    p.add_argument("--debug-now", default="")
    p.add_argument("--force", action="store_true", help="force execution even outside schedule")
    args = p.parse_args()

    now_sh = _now_sh(args.debug_now or None)
    d = _decide(now_sh, force=bool(args.force))
    base = {
        "tool": "tool_run_signal_risk_inspection_and_send",
        "now_sh": now_sh.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": args.mode,
        "fetch_mode": args.fetch_mode,
        "should_run": d.should_run,
        "phase": d.phase,
        "reason": d.reason,
    }
    if not d.should_run or not d.phase:
        _print({**base, "skipped": True, "success": True})
        return 0

    from plugins.notification.run_signal_risk_inspection import tool_run_signal_risk_inspection_and_send

    out = tool_run_signal_risk_inspection_and_send(
        phase=d.phase,
        mode=args.mode,
        fetch_mode=args.fetch_mode,
        debug_now=(args.debug_now or None) if args.fetch_mode == "test" else None,
    )
    ok = bool(isinstance(out, dict) and out.get("success") is True)
    _print({**base, "success": ok, "result": out})
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

