#!/usr/bin/env python3
"""
飞书通知发送器（运维通道）
读取 pending_notifications.json，通过飞书 webhook 发送消息

用法示例（在项目根目录执行）：
  # 将 data/pending_notifications.json 中未发送项输出为可投递记录（stdout）
  python3 scripts/alert_notify.py

  # 配合轮询：先跑一次 alert_poll 产出队列，再跑 notify 消费队列
  python3 scripts/alert_poll.py
  python3 scripts/alert_notify.py
"""

import json
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
QUEUE_FILE = DATA_DIR / "pending_notifications.json"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def load_pending() -> list:
    if QUEUE_FILE.exists():
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def mark_sent(queue: list):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def send_via_feishu_webhook(title: str, message: str) -> bool:
    from plugins.merged.send_feishu_notification import tool_send_feishu_notification

    out = tool_send_feishu_notification(
        notification_type="message",
        title=title,
        message=message,
    )
    ok = bool(isinstance(out, dict) and out.get("success") is True)
    # stdout 保留最小回执，便于 cron 日志审计
    print(json.dumps({"success": ok, "channel": "feishu_webhook", "detail": out}, ensure_ascii=False))
    return ok


def main():
    queue = load_pending()
    pending = [q for q in queue if not q.get("sent", True)]
    
    if not pending:
        print("No pending notifications.")
        return

    print(f"Found {len(pending)} pending notifications.")
    
    for item in pending:
        user_id = item["user_id"]
        user_name = item.get("user_name", user_id)
        message = item["message"]
        
        print(f"\n--- Sending to {user_name} ({user_id}) ---")
        ok = send_via_feishu_webhook(title=f"价格预警触发（{user_name}）", message=message)
        
        # 标记已发送
        item["sent"] = bool(ok)
        item["sent_at"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    mark_sent(queue)
    print("\nDone.")


if __name__ == "__main__":
    main()
