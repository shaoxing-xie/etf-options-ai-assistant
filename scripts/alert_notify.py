#!/usr/bin/env python3
"""
钉钉通知发送器
读取 pending_notifications.json，通过 OpenClaw message 工具发送私信
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
QUEUE_FILE = DATA_DIR / "pending_notifications.json"


def load_pending() -> list:
    if QUEUE_FILE.exists():
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def mark_sent(queue: list):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def send_via_openclaw(user_id: str, message: str) -> bool:
    """
    通过 openclaw message tool 发送钉钉私信
    使用 sessions_send 或直接输出供 agent 读取
    """
    # 输出到 stdout，供 cron 调用方（agent）捕获并发送
    print(f"__DINGTALK_PRIVATE__:{user_id}:{message}")
    return True


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
        send_via_openclaw(user_id, message)
        
        # 标记已发送
        item["sent"] = True
        item["sent_at"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    mark_sent(queue)
    print("\nDone.")


if __name__ == "__main__":
    main()
