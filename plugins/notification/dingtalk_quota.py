"""
钉钉通知配额与频率控制

目标：
- 只允许少量高优先级事件上钉钉（高/严重风险、高强度信号）
- 通过本地状态文件控制：时间去重、每日上限、月度硬上限
- 一旦达到月度上限，后续所有钉钉发送请求都会被本地熔断
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


STATE_PATH = os.path.expanduser("~/.openclaw/workspace/dingtalk_quota_state.json")

# 时间窗口：同一事件 key 在 WINDOW_MINUTES 内最多发送一次到钉钉
WINDOW_MINUTES = 30

# 每日钉钉发送硬上限（足够低，确保 5000/月 配额安全）
DAILY_LIMIT = 150

# 每月钉钉发送硬上限
MONTHLY_LIMIT = 5000


@dataclass
class QuotaDecision:
    allowed: bool
    reason: str


def _load_state() -> Dict[str, Any]:
    """读取本地配额状态文件。不存在时返回空结构。"""
    try:
        if not os.path.exists(STATE_PATH):
            return {
                "lastSends": {},  # key -> iso timestamp
                "dailyCounts": {},  # YYYY-MM-DD -> int
                "monthlyCounts": {},  # YYYY-MM -> int
            }
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 基本容错
        if not isinstance(data, dict):
            return {
                "lastSends": {},
                "dailyCounts": {},
                "monthlyCounts": {},
            }
        data.setdefault("lastSends", {})
        data.setdefault("dailyCounts", {})
        data.setdefault("monthlyCounts", {})
        return data
    except Exception:
        # 状态文件损坏时，回退为空状态，但仍然保护调用量（后续记录会从 0 开始）
        return {
            "lastSends": {},
            "dailyCounts": {},
            "monthlyCounts": {},
        }


def _save_state(state: Dict[str, Any]) -> None:
    """保存本地配额状态文件。"""
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        # 配额状态写入失败不应影响主流程，只作为最佳努力
        pass


def _now() -> datetime:
    return datetime.now()


def _event_key(event_type: str, symbol: str) -> str:
    """构造用于时间去重的事件 key。"""
    symbol_key = symbol or "UNKNOWN"
    return f"{event_type}:{symbol_key}"


def should_send_dingtalk(
    *,
    event_type: str,
    symbol: str,
    risk_level: Optional[str] = None,
    signal_strength: Optional[str] = None,
) -> QuotaDecision:
    """
    是否允许当前事件向钉钉发送提醒（不含真正的发送逻辑）。

    触发前提：
    - 风险预警：event_type="risk_alert" 且 risk_level in {"high", "critical"}
    - 信号提醒：event_type="signal_alert" 且 signal_strength == "strong"
    之后再应用时间去重、每日上限、月度上限。
    """
    # 1) 触发条件白名单
    event_type = event_type or ""
    lvl = (risk_level or "").lower()
    strength = (signal_strength or "").lower()

    if event_type == "risk_alert":
        if lvl not in {"high", "critical"}:
            return QuotaDecision(
                allowed=False,
                reason=f"skip_dingtalk: risk_level={risk_level!r} not in {{'high','critical'}}",
            )
    elif event_type == "signal_alert":
        if strength != "strong":
            return QuotaDecision(
                allowed=False,
                reason=f"skip_dingtalk: signal_strength={signal_strength!r} != 'strong'",
            )
    else:
        # 未知事件类型一律不打钉钉
        return QuotaDecision(
            allowed=False,
            reason=f"skip_dingtalk: unsupported event_type={event_type!r}",
        )

    # 2) 读取当前配额状态
    state = _load_state()
    now = _now()
    today_key = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")

    daily_counts = state.get("dailyCounts", {})
    monthly_counts = state.get("monthlyCounts", {})
    last_sends = state.get("lastSends", {})

    today_count = int(daily_counts.get(today_key, 0) or 0)
    month_count = int(monthly_counts.get(month_key, 0) or 0)

    # 3) 月度硬上限
    if month_count >= MONTHLY_LIMIT:
        return QuotaDecision(
            allowed=False,
            reason=f"blocked_dingtalk: monthly limit reached ({month_count} >= {MONTHLY_LIMIT})",
        )

    # 4) 每日上限
    if today_count >= DAILY_LIMIT:
        return QuotaDecision(
            allowed=False,
            reason=f"blocked_dingtalk: daily limit reached ({today_count} >= {DAILY_LIMIT})",
        )

    # 5) 时间去重（同一 event_type+symbol 在 WINDOW_MINUTES 内只发一次）
    key = _event_key(event_type, symbol)
    last_ts = last_sends.get(key)
    if isinstance(last_ts, str):
        try:
            last_dt = datetime.fromisoformat(last_ts)
            if now - last_dt < timedelta(minutes=WINDOW_MINUTES):
                return QuotaDecision(
                    allowed=False,
                    reason=f"skip_dingtalk: deduplicated within {WINDOW_MINUTES}min window",
                )
        except Exception:
            # 解析失败则忽略去重
            pass

    # 条件全部通过，允许发送。真正的计数更新在 record_dingtalk_send 中完成。
    return QuotaDecision(allowed=True, reason="ok")


def record_dingtalk_send(*, event_type: str, symbol: str) -> None:
    """
    在成功向钉钉发送消息后，更新配额状态：
    - 更新时间去重 key
    - 增加当日计数
    - 增加当月计数
    """
    state = _load_state()
    now = _now()
    today_key = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")

    daily_counts = state.get("dailyCounts", {})
    monthly_counts = state.get("monthlyCounts", {})
    last_sends = state.get("lastSends", {})

    key = _event_key(event_type, symbol)
    last_sends[key] = now.isoformat(timespec="seconds")

    daily_counts[today_key] = int(daily_counts.get(today_key, 0) or 0) + 1
    monthly_counts[month_key] = int(monthly_counts.get(month_key, 0) or 0) + 1

    state["lastSends"] = last_sends
    state["dailyCounts"] = daily_counts
    state["monthlyCounts"] = monthly_counts

    _save_state(state)

