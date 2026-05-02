"""
当进程环境未继承 FEISHU_WEBHOOK_URL 时（常见于 OpenClaw cron/agent 子进程），
从 ~/.openclaw/.env 按 KEY=VALUE 解析补全，避免仅依赖 os.getenv。

最后兜底：读取 ~/.openclaw/workspaces/shared/tools/send_feishu_webhook.py 内的
DEFAULT_WEBHOOK_URL（与 OpenClaw 内置脚本一致，避免 .env 误写 bash 自引用时全链路静默失败）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional


def read_feishu_webhook_from_openclaw_dotenv(
    env_path: Optional[Path] = None,
) -> str:
    """
    读取 ~/.openclaw/.env 中的 FEISHU_WEBHOOK_URL（不执行 shell 展开）。

    仅接受以 http 开头的值；忽略空值与自引用占位（如 "${FEISHU_WEBHOOK_URL:-}"）。
    """
    path = env_path or (Path.home() / ".openclaw" / ".env")
    try:
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""

    for raw_line in text.splitlines():
        s = raw_line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].strip()
        if "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        if key != "FEISHU_WEBHOOK_URL":
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        val = val.strip()
        if not val.lower().startswith("http"):
            continue
        if "${" in val or val.startswith('"${') or val.startswith("'${"):
            continue
        return val
    return ""


def read_feishu_webhook_from_openclaw_shared_tool() -> str:
    """从 OpenClaw 共享 send_feishu_webhook.py 提取 DEFAULT_WEBHOOK_URL（仅 feishu.cn bot hook 格式）。"""
    p = Path.home() / ".openclaw" / "workspaces" / "shared" / "tools" / "send_feishu_webhook.py"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    # 常见写法：两个相邻字符串字面值拼接 hook 前缀 + uuid
    m = re.search(
        r'"https://open\.feishu\.cn/open-apis/bot/v2/hook/"\s*(?:\r?\n\s*)?"([0-9a-fA-F\-]+)"',
        text,
    )
    if m:
        return f"https://open.feishu.cn/open-apis/bot/v2/hook/{m.group(1).strip()}"
    m2 = re.search(
        r"(https://open\.feishu\.cn/open-apis/bot/v2/hook/[0-9a-fA-F\-]+)",
        text,
    )
    return m2.group(1).strip() if m2 else ""


def effective_feishu_webhook_url() -> str:
    """进程环境 → ~/.openclaw/.env → OpenClaw 共享脚本 DEFAULT。"""
    w = (os.getenv("FEISHU_WEBHOOK_URL") or "").strip()
    if w.lower().startswith("http") and "${" not in w:
        return w
    w = read_feishu_webhook_from_openclaw_dotenv()
    if w:
        return w
    return read_feishu_webhook_from_openclaw_shared_tool()
