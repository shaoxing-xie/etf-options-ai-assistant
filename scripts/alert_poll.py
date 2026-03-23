#!/usr/bin/env python3
"""
预警轮询脚本（由 cron 触发，每10分钟执行一次）
- 检查所有活跃预警的条件
- 触发时通过 DingTalk 私信通知用户
- 触发后自动取消预警
"""

import json
import sys
from pathlib import Path

# 添加父目录到 path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

from alert_engine import (
    load_alerts, save_alerts, fetch_realtime,
    now_str
)

DATA_DIR = BASE_DIR / "data"


def run_poll():
    """执行一次轮询检查"""
    alerts = load_alerts()
    active = [a for a in alerts if a.get("active", True)]

    if not active:
        print(f"[{now_str()}] No active alerts. Skip.")
        return {"checked": 0, "triggered": 0}

    # 按标的分组去重
    codes = list(set(a["code"] for a in active))
    print(f"[{now_str()}] Checking {len(codes)} codes for {len(active)} alerts...")

    # 获取实时行情
    price_data = fetch_realtime(codes)
    
    if not price_data:
        print("[WARN] Failed to fetch any price data")
        return {"checked": len(active), "triggered": 0, "error": "no_price_data"}

    triggered = []

    for alert in active:
        code = alert["code"]
        if code not in price_data:
            continue

        info = price_data[code]
        current = info.get("current", 0)
        change_pct = info.get("change_pct", 0)
        target = alert["target"]
        alert_type = alert["alert_type"]
        triggered_now = False

        # 条件判断
        if alert_type == "above" and current >= target:
            triggered_now = True
        elif alert_type == "below" and current <= target:
            triggered_now = True
        elif alert_type == "pct_up" and change_pct >= target:
            triggered_now = True
        elif alert_type == "pct_down" and abs(change_pct) >= target:
            triggered_now = True

        if triggered_now:
            alert["active"] = False
            alert["triggered_at"] = now_str()
            triggered.append({
                "alert": alert,
                "current": current,
                "change_pct": change_pct,
                "price_info": info,
            })

    # 保存更新后的预警状态
    if triggered:
        save_alerts(alerts)
        print(f"[TRIGGERED] {len(triggered)} alerts triggered")
        
        # 写入触发日志
        _write_trigger_log(triggered)
        
        # 写入待发送队列
        _enqueue_notifications(triggered)

    result = {
        "checked": len(active),
        "codes": len(codes),
        "triggered": len(triggered),
        "items": [
            {
                "code": t["alert"]["code"],
                "user": t["alert"]["user_name"],
                "condition": f"{t['alert']['type_label']} → {t['alert']['target']}",
                "current": t["current"],
                "change_pct": t["change_pct"],
            }
            for t in triggered
        ]
    }
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _write_trigger_log(triggered: list):
    """写入触发日志"""
    log_file = DATA_DIR / "trigger_log.json"
    logs = []
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except:
            pass
    
    for t in triggered:
        logs.append({
            "alert_id": t["alert"]["id"],
            "user_id": t["alert"]["user_id"],
            "user_name": t["alert"]["user_name"],
            "code": t["alert"]["code"],
            "alert_type": t["alert"]["alert_type"],
            "target": t["alert"]["target"],
            "current": t["current"],
            "change_pct": t["change_pct"],
            "triggered_at": t["alert"]["triggered_at"],
        })
    
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def _enqueue_notifications(triggered: list):
    """将触发的预警加入钉钉私信发送队列"""
    queue_file = DATA_DIR / "pending_notifications.json"
    queue = []
    if queue_file.exists():
        try:
            with open(queue_file, "r", encoding="utf-8") as f:
                queue = json.load(f)
        except:
            pass
    
    for t in triggered:
        alert = t["alert"]
        current = t["current"]
        change_pct = t["change_pct"]
        
        msg = (
            f"🚨 **价格预警触发！**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 **标的**：{alert['code']}\n"
            f"🔔 **条件**：{alert['type_label']} → {alert['target']}\n"
            f"📊 **当前价**：{current}（{change_pct:+.2f}%）\n"
            f"⏰ **触发时间**：{now_str()}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✅ 本预警已自动取消"
        )
        
        queue.append({
            "user_id": alert["user_id"],
            "user_name": alert["user_name"],
            "message": msg,
            "type": "alert_trigger",
            "created_at": now_str(),
            "sent": False,
        })
    
    with open(queue_file, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    run_poll()
