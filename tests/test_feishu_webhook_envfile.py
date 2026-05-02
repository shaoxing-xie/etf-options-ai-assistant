"""从 ~/.openclaw/.env 解析 FEISHU_WEBHOOK_URL（子进程无继承环境时）。"""

from __future__ import annotations

from pathlib import Path

from src.feishu_webhook_envfile import (
    effective_feishu_webhook_url,
    read_feishu_webhook_from_openclaw_dotenv,
    read_feishu_webhook_from_openclaw_shared_tool,
)


def test_read_from_file_when_env_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
    envf = tmp_path / ".env"
    envf.write_text(
        "FOO=1\nFEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/dummy\n",
        encoding="utf-8",
    )
    got = read_feishu_webhook_from_openclaw_dotenv(env_path=envf)
    assert got == "https://open.feishu.cn/open-apis/bot/v2/hook/dummy"


def test_effective_prefers_process_env(tmp_path, monkeypatch):
    envf = tmp_path / ".env"
    envf.write_text(
        "FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/fromfile\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "FEISHU_WEBHOOK_URL", "https://open.feishu.cn/open-apis/bot/v2/hook/fromenv"
    )
    # effective uses getenv first — patch file path by monkeypatching home? effective uses Path.home()
    # So we only assert env wins when set
    assert effective_feishu_webhook_url().endswith("fromenv")


def test_fallback_from_openclaw_shared_tool(tmp_path, monkeypatch):
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    toolp = (
        tmp_path
        / ".openclaw"
        / "workspaces"
        / "shared"
        / "tools"
        / "send_feishu_webhook.py"
    )
    toolp.parent.mkdir(parents=True)
    toolp.write_text(
        'DEFAULT_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"\n',
        encoding="utf-8",
    )
    assert (
        read_feishu_webhook_from_openclaw_shared_tool()
        == "https://open.feishu.cn/open-apis/bot/v2/hook/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    assert effective_feishu_webhook_url().endswith("eeeeeeeeeeee")


def test_skip_self_referential_placeholder(tmp_path, monkeypatch):
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
    envf = tmp_path / ".env"
    envf.write_text(
        'FEISHU_WEBHOOK_URL="${FEISHU_WEBHOOK_URL:-}"\n'
        "FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/real\n",
        encoding="utf-8",
    )
    got = read_feishu_webhook_from_openclaw_dotenv(env_path=envf)
    assert got.endswith("/real")
