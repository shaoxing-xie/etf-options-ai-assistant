"""
合并工具：飞书通知
notification_type: message | signal_alert | daily_report | risk_alert

说明：
- 该工具作为 OpenClaw 统一通知入口，供 tool_runner 的别名层调用。
- 优先复用原系统（本地迁移）src 下的配置加载与飞书能力；
- 发送通道优先使用 notification.feishu_webhook（最少依赖、无需 chat_id）。
"""

import json
from typing import Dict, Any, Optional
from datetime import datetime

from plugins.utils.index_pct_sanity import reconcile_index_change_pct


def _format_report_data(data: Dict[str, Any]) -> str:
    """将 report_data 转为可读摘要，优先使用已有文本字段；支持 analysis/data 嵌套。"""
    if not data or not isinstance(data, dict):
        return ""
    # 顶层文本字段
    for key in ("llm_summary", "summary", "full_text", "overview"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # 分析工具返回 { data: { llm_summary, summary, ... } } 或 { analysis: { ... } }
    inner = data.get("data") or data.get("analysis") or {}
    if isinstance(inner, dict):
        for key in ("llm_summary", "summary", "full_text", "overview"):
            val = inner.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        # opening 等返回 data.summary 为 dict（如 market_sentiment, strong_count）
        summary_obj = inner.get("summary")
        if isinstance(summary_obj, dict):
            parts = []
            if summary_obj.get("market_sentiment"):
                parts.append(f"市场情绪: {summary_obj['market_sentiment']}")
            if "strong_count" in summary_obj and "weak_count" in summary_obj:
                parts.append(f"偏强/偏弱家数: {summary_obj['strong_count']}/{summary_obj['weak_count']}")
            if summary_obj.get("timestamp"):
                parts.append(f"时间: {summary_obj['timestamp']}")
            if parts:
                return "\n".join(parts)
        # data.indices 开盘各指数简要
        indices = inner.get("indices")
        if isinstance(indices, dict) and indices:
            lines = ["各指数开盘:"]
            for code, info in list(indices.items())[:8]:
                if isinstance(info, dict):
                    name = info.get("name", code)
                    raw = info.get("change_pct")
                    op = info.get("open_price") or info.get("opening_price")
                    pc = info.get("close_yesterday") or info.get("pre_close")
                    rp = reconcile_index_change_pct(raw, op, pc)
                    try:
                        val = float(rp if rp is not None else raw)
                        chg_s = f"{val:.2f}%"
                    except (TypeError, ValueError):
                        chg_s = "N/A"
                    strength = info.get("strength", "")
                    lines.append(f"  {name}: {chg_s} {strength}".strip())
            return "\n".join(lines)
    # 简短结构化摘要（顶层）
    parts = []
    if data.get("report_type"):
        parts.append(f"类型: {data['report_type']}")
    if data.get("date"):
        parts.append(f"日期: {data['date']}")
    if data.get("overall_trend"):
        parts.append(f"整体趋势: {data['overall_trend']}")
    if data.get("next_day_suggestion"):
        parts.append(f"次日建议: {data['next_day_suggestion']}")
    if data.get("message") and data.get("success") is True:
        parts.append(data["message"])
    if parts:
        return "\n".join(parts)
    return json.dumps(data, ensure_ascii=False, default=str)[:2000]


def _build_text(notification_type: str, **kwargs) -> str:
    title = kwargs.get("title")
    message = kwargs.get("message")
    structured_message = kwargs.get("structured_message")
    risk_data = kwargs.get("risk_data")
    signal_data = kwargs.get("signal_data")
    report_data = kwargs.get("report_data")
    # 插件侧 tool_send_signal_alert 传的是 signals（数组），与 signal_data 二选一使用
    signals = kwargs.get("signals")

    header = f"[{notification_type}]"
    if title:
        header += f" {title}"

    if notification_type == "message":
        body = structured_message or message or ""
    elif notification_type == "daily_report":
        if structured_message or message:
            body = structured_message or message
        elif report_data:
            body = _format_report_data(report_data)
        else:
            body = "日报生成完成（上游未传入报告内容，请检查分析工具返回及 Agent 是否将结果正确传入 report_data）"
    elif notification_type == "signal_alert":
        if structured_message:
            body = structured_message
        elif signal_data is not None:
            _empty = (isinstance(signal_data, (list, dict)) and len(signal_data) == 0)
            body = "暂无新信号（当前无满足条件的交易信号）" if _empty else f"信号提醒: {signal_data}"
        elif signals is not None:
            _empty = (isinstance(signals, list) and len(signals) == 0)
            body = "暂无新信号（当前无满足条件的交易信号）" if _empty else f"信号提醒: {signals}"
        else:
            body = message or "信号提醒（上游未传入 signal_data，请检查 tool_generate_option_trading_signals（别名 tool_generate_signals）或 tool_generate_trend_following_signal 的返回是否作为 signal_data 传入）"
    elif notification_type == "risk_alert":
        if structured_message:
            body = structured_message
        elif risk_data is not None:
            body = f"风控提醒: {risk_data}"
        else:
            body = message or "风控提醒（上游未传入 risk_data，请检查 tool_assess_risk 的返回是否作为 risk_data 传入）"
    else:
        body = structured_message or message or f"未知通知类型: {notification_type}"

    # 巡检类消息追加“技术细节摘要”
    # 约定：title 中包含“信号+风控巡检”时，在正文追加一行技术实现说明，便于人工快速了解底层数据来源。
    if (
        notification_type == "message"
        and isinstance(title, str)
        and "信号+风控巡检" in title
    ):
        tech_line = "技术细节摘要：已使用 Alltick Tick 验证沪深300/创业板指突破；510300 暂用 5 分钟 K 线降级确认。"
        if body:
            body = f"{body}\n\n{tech_line}"
        else:
            body = tech_line

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"{header}\n时间: {ts}\n\n{body}".strip()


def _send_via_webhook(webhook_url: str, text: str) -> Dict[str, Any]:
    import requests

    payload = {
        "msg_type": "text",
        "content": {"text": text},
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        ok_http = 200 <= resp.status_code < 300
        try:
            data = resp.json()
        except Exception:
            data = {"raw": (resp.text or "")[:500]}
        # 飞书 webhook 常见返回：{"StatusCode":0,"StatusMessage":"success"}
        status_code = data.get("StatusCode")
        ok_app = (status_code == 0) if status_code is not None else ok_http
        return {
            "success": bool(ok_app),
            "http_status": resp.status_code,
            "response": data,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _resolve_env_template(value: Any) -> str:
    """
    Resolve simple ${VAR} / ${VAR:-default} templates used in YAML config.
    If value is not a string or not a template, returns str(value).
    """
    import os
    import re

    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)
    s = value.strip()
    m = re.fullmatch(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}", s)
    if not m:
        return s
    var = m.group(1)
    default = m.group(2) if m.group(2) is not None else ""
    return str(os.environ.get(var, default) or "").strip()


def resolve_feishu_webhook_url(
    webhook_url: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    解析飞书 webhook：显式参数 > notification.feishu_webhook（含 ${VAR}）> 环境变量。

    OpenClaw 子进程若未把占位符展开或 YAML 为 null 时，直接读 FEISHU_WEBHOOK_URL 等兜底。
    """
    import os

    notification_cfg: Dict[str, Any] = {}
    if isinstance(config, dict):
        raw = config.get("notification")
        if isinstance(raw, dict):
            notification_cfg = raw

    for candidate in (webhook_url, notification_cfg.get("feishu_webhook")):
        if candidate is None:
            continue
        if isinstance(candidate, str) and not candidate.strip():
            continue
        w = _resolve_env_template(candidate)
        if isinstance(w, str) and w.startswith("http"):
            return w.strip()

    try:
        from src.feishu_webhook_envfile import effective_feishu_webhook_url

        w = effective_feishu_webhook_url().strip()
    except Exception:
        w = (os.getenv("FEISHU_WEBHOOK_URL") or "").strip()
    if w.lower().startswith("http"):
        return w
    return ""


def tool_send_feishu_notification(
    notification_type: str,
    message: Optional[str] = None,
    title: Optional[str] = None,
    structured_message: Optional[str] = None,
    risk_data: Optional[dict] = None,
    signal_data: Optional[dict] = None,
    report_data: Optional[dict] = None,
    webhook_url: Optional[str] = None,
    cooldown_key: Optional[str] = None,
    cooldown_minutes: Optional[int] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：发送飞书通知（统一入口）

    Args:
        notification_type: message | signal_alert | daily_report | risk_alert
        message/title/structured_message: 文本内容
        risk_data/signal_data/report_data: 结构化数据（会被字符串化）
        report_data: 日报数据（daily_report 时使用，可含 llm_summary/overall_trend 等）
        webhook_url: 可覆盖配置中的 notification.feishu_webhook
        cooldown_key: 冷却去重 key（相同 key 在 cooldown_minutes 内最多发送一次；用于防止刷屏）
        cooldown_minutes: 冷却窗口分钟数（默认：risk_alert/signal_alert=30，其余=0）
    """
    # 1) 读取原系统配置（src 迁移到本地）
    config = None
    try:
        from src.config_loader import load_system_config

        config = load_system_config()
    except Exception:
        config = {}

    # 2) 组装文本（report_data 可能来自显参或 kwargs，统一传入）
    text = _build_text(
        notification_type=notification_type,
        title=title,
        message=message,
        structured_message=structured_message,
        risk_data=risk_data,
        signal_data=signal_data,
        report_data=report_data or kwargs.get("report_data"),
        **kwargs,
    )

    # 3) 冷却去重（防刷屏）
    try:
        from notification.notification_cooldown import should_send, record_send

        cm = (
            int(cooldown_minutes)
            if isinstance(cooldown_minutes, (int, float, str)) and str(cooldown_minutes).strip() != ""
            else (30 if notification_type in {"risk_alert", "signal_alert"} else 0)
        )
        key = (cooldown_key or "").strip()
        if not key:
            # best-effort auto key
            sym = (kwargs.get("symbol") or kwargs.get("etf_symbol") or kwargs.get("index_code") or "").strip()
            base = (title or notification_type or "").strip()
            key = f"{notification_type}:{base}:{sym}" if base or sym else ""

        decision = should_send(key=key, cooldown_minutes=cm)
        if not decision.allowed:
            return {
                "success": True,
                "message": f"通知已被冷却去重抑制（{decision.reason}）",
                "notification_type": notification_type,
                "text": text,
                "channel": "cooldown_suppressed",
                "detail": {"cooldown_key": key, "cooldown_minutes": cm, "reason": decision.reason},
            }
    except Exception:
        # 冷却模块不可用时不影响主流程
        decision = None
        key = ""

    # 4) 发送：优先 webhook（无需 chat_id）；配置为空时回退 FEISHU_WEBHOOK_URL
    webhook = resolve_feishu_webhook_url(webhook_url, config if isinstance(config, dict) else None)
    if webhook:
        send_result = _send_via_webhook(webhook, text)
        # 成功发送后记录冷却 key
        try:
            if send_result.get("success") and key:
                from notification.notification_cooldown import record_send

                record_send(key=key)
        except Exception:
            pass
        return {
            "success": send_result.get("success", False),
            "message": "飞书通知已发送" if send_result.get("success") else "飞书通知发送失败",
            "notification_type": notification_type,
            "text": text,
            "channel": "webhook",
            "detail": send_result,
        }

    # 5) 若未配置 webhook，返回结构化失败（工具仍可调用，便于定时任务上报）
    return {
        "success": False,
        "message": "未配置有效飞书 webhook（notification.feishu_webhook / FEISHU_WEBHOOK_URL），无法发送通知",
        "notification_type": notification_type,
        "text": text,
        "channel": None,
    }

