#!/usr/bin/env python3
"""
A股价格预警引擎 (Alert Engine)
- 读写 alerts.json
- 条件判断与触发
- 钉钉私信通知
"""

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ALERTS_FILE = DATA_DIR / "alerts.json"

CST = timezone(timedelta(hours=8))

MAX_ALERTS_PER_USER = 5  # 每人最多同时5条
ALERT_TYPES = {
    "above":    "突破上限",      # 当前价 >= 目标价
    "below":    "跌破下限",      # 当前价 <= 目标价
    "pct_up":   "涨幅超阈值",   # 涨幅 >= 阈值(%)
    "pct_down": "跌幅超阈值",   # 跌幅 >= 阈值(%)
}


# ---------------------------------------------------------------------------
# 数据层
# ---------------------------------------------------------------------------
def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_alerts() -> list:
    if ALERTS_FILE.exists():
        with open(ALERTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_alerts(alerts: list):
    _ensure_data_dir()
    with open(ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def user_alert_count(user_id: str) -> int:
    """统计某用户现有预警数量"""
    return sum(1 for a in load_alerts() if a["user_id"] == user_id and a.get("active", True))


def parse_alert_args(text: str) -> dict | None:
    """
    解析用户指令，返回结构化参数。
    支持格式：
      #预警 600900 above 28.0
      #预警 510300 below 4.50
      #预警 600519 pct_up 3.0
      #预警 000001 pct_down 1.5
    """
    parts = text.strip().split()
    if len(parts) < 4 or parts[0] != "#预警":
        return None

    code = parts[1].strip()
    alert_type = parts[2].strip().lower()

    if alert_type not in ALERT_TYPES:
        return None

    try:
        target = float(parts[3].strip())
    except ValueError:
        return None

    return {
        "code": code,
        "alert_type": alert_type,
        "target": target,
        "type_label": ALERT_TYPES[alert_type],
    }


# ---------------------------------------------------------------------------
# 命令：创建预警
# ---------------------------------------------------------------------------
def create_alert(user_id: str, user_name: str, code: str, alert_type: str, target: float) -> dict:
    """
    创建预警，返回 {success, message, alert_id}
    """
    # 数量限制
    existing = load_alerts()
    user_count = sum(1 for a in existing if a["user_id"] == user_id and a.get("active", True))
    if user_count >= MAX_ALERTS_PER_USER:
        return {
            "success": False,
            "message": f"⚠️ 每人最多同时{MAX_ALERTS_PER_USER}条预警，当前已有{user_count}条。请先取消部分预警再添加。",
        }

    alert = {
        "id": f"ALT{int(time.time())}_{user_id[-4:]}",
        "user_id": user_id,
        "user_name": user_name,
        "code": code,
        "alert_type": alert_type,
        "type_label": ALERT_TYPES[alert_type],
        "target": target,
        "created_at": now_str(),
        "triggered_at": None,
        "active": True,
    }
    existing.append(alert)
    save_alerts(existing)

    return {
        "success": True,
        "alert_id": alert["id"],
        "message": f"✅ 预警已创建\n"
                   f"  标的：{code}\n"
                   f"  条件：{ALERT_TYPES[alert_type]} → {target}\n"
                   f"  ID：{alert['id']}",
    }


# ---------------------------------------------------------------------------
# 命令：查询预警
# ---------------------------------------------------------------------------
def list_alerts(user_id: str = None) -> list:
    """返回预警列表，可指定user_id过滤"""
    alerts = load_alerts()
    if user_id:
        alerts = [a for a in alerts if a["user_id"] == user_id and a.get("active", True)]
    else:
        alerts = [a for a in alerts if a.get("active", True)]
    return alerts


# ---------------------------------------------------------------------------
# 命令：取消预警
# ---------------------------------------------------------------------------
def cancel_alert(user_id: str, alert_id: str) -> dict:
    """取消预警（仅本人可取消）"""
    alerts = load_alerts()
    found = None
    for a in alerts:
        if a["id"] == alert_id:
            found = a
            break

    if not found:
        return {"success": False, "message": f"❌ 未找到预警 {alert_id}"}

    if found["user_id"] != user_id:
        return {"success": False, "message": "❌ 只能取消自己的预警"}

    found["active"] = False
    save_alerts(alerts)
    return {"success": True, "message": f"✅ 预警 {alert_id} 已取消"}


def cancel_all_alerts(user_id: str) -> dict:
    """取消某用户所有预警"""
    alerts = load_alerts()
    count = 0
    for a in alerts:
        if a["user_id"] == user_id and a.get("active", True):
            a["active"] = False
            count += 1
    save_alerts(alerts)
    return {"success": True, "message": f"✅ 已取消全部 {count} 条预警"}


# ---------------------------------------------------------------------------
# P1：轮询触发引擎
# ---------------------------------------------------------------------------
def fetch_realtime(codes: list[str]) -> dict:
    """
    批量获取实时行情。
    调用 tool_fetch_stock_realtime（通过 CLI 或内嵌方式）。
    返回 {code: {current, change_pct, ...}}
    """
    # 通过命令行调用 mootdx 获取数据（与现有工具保持一致）
    result = {}
    code_str = ",".join(codes)
    try:
        # 尝试使用 Python 内置的数据获取
        sys.path.insert(0, str(BASE_DIR))
        from scripts.fetch_stock_realtime import fetch_batch
        result = fetch_batch(codes)
    except ImportError:
        # 回退到简单的数据获取
        pass
    return result


def check_and_trigger():
    """
    核心轮询函数：
    1. 加载所有活跃预警
    2. 按标的分组，批量获取行情
    3. 判断条件，触发通知
    4. 自动取消已触发的预警
    """
    alerts = load_alerts()
    active = [a for a in alerts if a.get("active", True)]

    if not active:
        print("No active alerts.")
        return []

    # 按标的分组
    codes = list(set(a["code"] for a in active))
    print(f"Checking {len(codes)} codes for {len(active)} alerts...")

    # 获取实时行情
    price_data = fetch_realtime(codes)
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

        if alert_type == "above" and current >= target:
            triggered_now = True
        elif alert_type == "below" and current <= target:
            triggered_now = True
        elif alert_type == "pct_up" and change_pct >= target:
            triggered_now = True
        elif alert_type == "pct_down" and abs(change_pct) >= target:
            triggered_now = True

        if triggered_now:
            # 更新状态
            alert["active"] = False
            alert["triggered_at"] = now_str()
            triggered.append({
                "alert": alert,
                "current": current,
                "change_pct": change_pct,
            })

    if triggered:
        save_alerts(alerts)
        # 发送通知
        for t in triggered:
            send_notification(t)

    return triggered


def send_notification(trigger_info: dict):
    """
    通过钉钉私信发送预警通知
    """
    alert = trigger_info["alert"]
    current = trigger_info["current"]
    change_pct = trigger_info["change_pct"]

    # 构造通知消息
    msg = (
        f"🚨 **价格预警触发**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📌 标的：**{alert['code']}**\n"
        f"🔔 条件：{alert['type_label']} → {alert['target']}\n"
        f"📊 当前价：**{current}**（{change_pct:+.2f}%）\n"
        f"⏰ 触发时间：{now_str()}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⚠️ 本预警已自动取消"
    )

    print(f"[ALERT] {alert['code']} {alert['type_label']} triggered for {alert['user_name']}")
    print(msg)

    # 调用钉钉发送（通过环境变量或配置文件获取 webhook）
    dingtalk_msg_private(alert["user_id"], msg)

    return msg


def dingtalk_msg_private(user_id: str, message: str):
    """
    发送钉钉私信
    方式1：通过 openclaw message tool（由外层调用）
    方式2：通过钉钉 API（需要 access_token）
    这里输出 JSON 供外层脚本读取并发送
    """
    # 写入待发送队列
    _ensure_data_dir()
    queue_file = DATA_DIR / "pending_notifications.json"
    queue = []
    if queue_file.exists():
        with open(queue_file, "r", encoding="utf-8") as f:
            queue = json.load(f)

    queue.append({
        "user_id": user_id,
        "message": message,
        "created_at": now_str(),
        "sent": False,
    })

    with open(queue_file, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: alert_engine.py <command> [args]")
        print("Commands: create, list, cancel, cancel_all, check")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "create":
        # python alert_engine.py create <user_id> <user_name> <code> <type> <target>
        if len(sys.argv) < 7:
            print("Usage: create <user_id> <user_name> <code> <type> <target>")
            sys.exit(1)
        result = create_alert(
            user_id=sys.argv[2],
            user_name=sys.argv[3],
            code=sys.argv[4],
            alert_type=sys.argv[5],
            target=float(sys.argv[6]),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "list":
        user_id = sys.argv[2] if len(sys.argv) > 2 else None
        alerts = list_alerts(user_id)
        print(json.dumps(alerts, ensure_ascii=False, indent=2))

    elif cmd == "cancel":
        if len(sys.argv) < 4:
            print("Usage: cancel <user_id> <alert_id>")
            sys.exit(1)
        result = cancel_alert(sys.argv[2], sys.argv[3])
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "cancel_all":
        if len(sys.argv) < 3:
            print("Usage: cancel_all <user_id>")
            sys.exit(1)
        result = cancel_all_alerts(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "check":
        triggered = check_and_trigger()
        print(f"Triggered {len(triggered)} alerts.")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
