"""
A股市场时段细分（集合竞价/连续竞价/午休/收盘集合竞价/盘后/隔夜）。

动机：
- 现有 tool_check_trading_status 只有粗粒度状态（before_open/trading/lunch_break/after_close...）
- 交易助手需要更细的“可做什么/不该做什么”的守卫逻辑，避免把集合竞价/午休/盘后误当成连续交易波动
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional

import json
import os

import pytz


@dataclass(frozen=True)
class AShareSessionTimes:
    preopen_start: time = time.fromisoformat("09:15")
    call_auction_end: time = time.fromisoformat("09:25")
    preopen_pause_end: time = time.fromisoformat("09:30")
    morning_end: time = time.fromisoformat("11:30")
    afternoon_start: time = time.fromisoformat("13:00")
    closing_auction_start: time = time.fromisoformat("14:57")
    close: time = time.fromisoformat("15:00")


def _load_holidays_from_env() -> List[str]:
    # 兼容 tool_check_trading_status 的环境变量命名
    holidays_str = os.getenv("TRADING_HOURS_HOLIDAYS_2026", "[]")
    try:
        holidays = json.loads(holidays_str) if holidays_str else []
        if isinstance(holidays, list):
            return [str(x) for x in holidays]
    except Exception:
        pass
    return []


def _is_trading_day(now: datetime, holidays: List[str]) -> bool:
    weekday = now.weekday()  # 0=Mon ... 6=Sun
    if weekday >= 5:
        return False
    date_str = now.strftime("%Y%m%d")
    return date_str not in holidays


def get_a_share_market_regime(
    *,
    timezone: str = "Asia/Shanghai",
    now: Optional[str] = None,
    holidays: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    细分 A股市场时段，并给出建议的策略降级模式。

    Args:
        timezone: 时区（默认 Asia/Shanghai）
        now: 可选，用于测试的时间（ISO 格式，如 2026-03-06T09:20:00+08:00 或 2026-03-06 09:20:00）
        holidays: 可选，YYYYMMDD 列表；为空时从环境变量加载

    Returns:
        OpenClaw tool result dict: {success, data, message?}
    """
    try:
        tz = pytz.timezone(timezone)
        if now:
            # 容错解析：支持 "YYYY-MM-DD HH:MM:SS" 与 ISO
            try:
                parsed = datetime.fromisoformat(now.replace("Z", "+00:00"))
            except Exception:
                parsed = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
            if parsed.tzinfo is None:
                parsed = tz.localize(parsed)
            current_dt = parsed.astimezone(tz)
        else:
            current_dt = datetime.now(tz)

        current_time = current_dt.time()
        hs = holidays if holidays is not None else _load_holidays_from_env()
        is_td = _is_trading_day(current_dt, hs)

        # phase: 细分时段（对外输出稳定 enum）
        # - non_trading_day
        # - preopen (09:15 前)
        # - call_auction (09:15-09:25)
        # - preopen_pause (09:25-09:30)
        # - morning_session (09:30-11:30)
        # - lunch_break (11:30-13:00)
        # - afternoon_session (13:00-14:57)
        # - closing_auction (14:57-15:00)
        # - after_close (15:00 后)
        times = AShareSessionTimes()

        if not is_td:
            phase = "non_trading_day"
            can_trade = False
        elif current_time < times.preopen_start:
            phase = "preopen"
            can_trade = False
        elif times.preopen_start <= current_time < times.call_auction_end:
            phase = "call_auction"
            # 集合竞价可挂单，但成交不连续；对信号需降级
            can_trade = True
        elif times.call_auction_end <= current_time < times.preopen_pause_end:
            phase = "preopen_pause"
            can_trade = False
        elif times.preopen_pause_end <= current_time <= times.morning_end:
            phase = "morning_session"
            can_trade = True
        elif times.morning_end < current_time < times.afternoon_start:
            phase = "lunch_break"
            can_trade = False
        elif times.afternoon_start <= current_time < times.closing_auction_start:
            phase = "afternoon_session"
            can_trade = True
        elif times.closing_auction_start <= current_time <= times.close:
            phase = "closing_auction"
            can_trade = True
        else:
            phase = "after_close"
            can_trade = False

        # 建议模式：用于上层编排节流/降级
        if phase in ("non_trading_day", "after_close"):
            recommended_mode = "after_close"
        elif phase in ("preopen", "call_auction", "preopen_pause"):
            recommended_mode = "before_open"
        elif phase in ("lunch_break",):
            recommended_mode = "light"
        else:
            recommended_mode = "normal"

        # 计算下一个切换点（便于调度与用户提示）
        transition_points = [
            ("call_auction", times.preopen_start),
            ("preopen_pause", times.call_auction_end),
            ("morning_session", times.preopen_pause_end),
            ("lunch_break", times.morning_end),
            ("afternoon_session", times.afternoon_start),
            ("closing_auction", times.closing_auction_start),
            ("after_close", times.close),
        ]

        next_transition = None
        remaining_minutes = 0
        if is_td:
            for next_phase, tp in transition_points:
                if current_time < tp:
                    nt = tz.localize(datetime.combine(current_dt.date(), tp))
                    next_transition = {
                        "next_phase": next_phase,
                        "next_time": nt.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    remaining_minutes = int(max(0, (nt - current_dt).total_seconds() / 60))
                    break

            # after_close：给出下一个交易日 09:15
            if next_transition is None and phase == "after_close":
                nxt = current_dt
                days_checked = 0
                while days_checked < 14:
                    nxt += timedelta(days=1)
                    days_checked += 1
                    if _is_trading_day(nxt, hs):
                        break
                nt = tz.localize(datetime.combine(nxt.date(), times.preopen_start))
                next_transition = {
                    "next_phase": "preopen",
                    "next_time": nt.strftime("%Y-%m-%d %H:%M:%S"),
                }
                remaining_minutes = int(max(0, (nt - current_dt).total_seconds() / 60))

        return {
            "success": True,
            "data": {
                "phase": phase,
                "is_trading_day": is_td,
                "can_trade": can_trade,
                "recommended_mode": recommended_mode,
                "current_time": current_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": timezone,
                "next_transition": next_transition,
                "remaining_minutes": remaining_minutes,
            },
        }
    except Exception as e:
        return {"success": False, "message": f"A股市场时段判定失败: {e}", "data": None}


def tool_get_a_share_market_regime(
    timezone: str = "Asia/Shanghai",
    now: Optional[str] = None,
    holidays: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """OpenClaw 工具：A股市场时段细分。"""
    return get_a_share_market_regime(timezone=timezone, now=now, holidays=holidays)

