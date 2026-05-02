#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class Decision:
    active: bool
    decision: str  # "pause" | "keep"
    reason: str
    until: str
    degraded: bool


def _today_shanghai() -> str:
    try:
        import pytz  # type: ignore

        tz = pytz.timezone("Asia/Shanghai")
        return datetime.now(tz).strftime("%Y-%m-%d")
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%d")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _is_extreme_from_sentiment_check(snap: Dict[str, Any]) -> tuple[bool, str, bool]:
    score = snap.get("overall_score")
    stage = str(snap.get("sentiment_stage") or "")
    degraded = bool(snap.get("degraded"))

    is_extreme = False
    if isinstance(score, (int, float)):
        try:
            is_extreme = float(score) >= 85 or float(score) <= 20
        except Exception:
            pass
    if any(x in stage for x in ("冰点", "退潮", "极端")):
        is_extreme = True

    reason = f"score={score} stage={stage}".strip()
    if not snap:
        degraded = True
        reason = "sentiment_check_missing"
    return is_extreme, reason, degraded


def _next_trading_day_0930_shanghai(from_day: str) -> str:
    """
    输出形如 "YYYY-MM-DD 09:30:00"（Asia/Shanghai 语义）。
    若判断失败，退化为 from_day+1。
    """
    try:
        from plugins.utils.trading_day import is_trading_day  # type: ignore
        import pytz  # type: ignore

        tz = pytz.timezone("Asia/Shanghai")
        d = datetime.strptime(from_day, "%Y-%m-%d").replace(tzinfo=tz)
        for _ in range(14):
            d = d + timedelta(days=1)
            if is_trading_day(d):
                return d.strftime("%Y-%m-%d 09:30:00")
        return (d + timedelta(days=1)).strftime("%Y-%m-%d 09:30:00")
    except Exception:
        try:
            d = datetime.strptime(from_day, "%Y-%m-%d") + timedelta(days=1)
            return d.strftime("%Y-%m-%d 09:30:00")
        except Exception:
            return ""


def decide(trade_date: str) -> Decision:
    snap = _read_json(ROOT / "data" / "sentiment_check" / f"{trade_date}.json")
    extreme, reason, degraded = _is_extreme_from_sentiment_check(snap)
    active = bool(extreme)
    decision = "pause" if active else "keep"
    until = _next_trading_day_0930_shanghai(trade_date) if active else ""
    return Decision(
        active=active,
        decision=decision,
        reason=reason,
        until=until,
        degraded=degraded,
    )


def main() -> int:
    # 统一口径：cron 语义日优先 ORCH_TRADE_DATE，否则按上海自然日。
    trade_date = (os.environ.get("ORCH_TRADE_DATE") or "").strip() or _today_shanghai()
    d = decide(trade_date)

    from src.screening_ops import tool_set_screening_emergency_pause
    from src.screening_gate_files import emergency_pause_path

    pause_path = emergency_pause_path()
    before_mtime = 0
    try:
        before_mtime = int(pause_path.stat().st_mtime)
    except Exception:
        before_mtime = 0

    out = tool_set_screening_emergency_pause(active=d.active, reason=d.reason, until=d.until)
    ok = bool(out.get("success"))
    after_mtime = 0
    try:
        after_mtime = int(pause_path.stat().st_mtime)
    except Exception:
        after_mtime = 0

    file_updated = after_mtime > before_mtime or (before_mtime == 0 and after_mtime > 0)
    ts_ms = int(datetime.now(UTC).timestamp() * 1000)

    if ok and file_updated:
        print(
            json.dumps(
                {
                    "run_status": "ok",
                    "decision": d.decision,
                    "pause_active": d.active,
                    "trade_date": trade_date,
                    "run_quality": "ok_degraded" if d.degraded else "ok_full",
                    "pause_path": str(pause_path),
                    "ts": ts_ms,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if ok and not file_updated:
        print(
            json.dumps(
                {
                    "run_status": "error",
                    "reason": "ERROR_EMERGENCY_PAUSE_NOT_UPDATED",
                    "trade_date": trade_date,
                    "pause_path": str(pause_path),
                    "before_mtime": before_mtime,
                    "after_mtime": after_mtime,
                    "ts": ts_ms,
                },
                ensure_ascii=False,
            )
        )
        return 1

    print(
        json.dumps(
            {"run_status": "error", "reason": str(out.get("error") or "unknown"), "trade_date": trade_date, "ts": ts_ms},
            ensure_ascii=False,
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

