"""
Send Feishu interactive card via webhook.

Feishu bot webhook supports sending:
- msg_type: "interactive" with {card: {...}}

This tool complements tool_send_feishu_notification (text-only).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union


def _load_webhook_from_config() -> Optional[str]:
    try:
        from src.config_loader import load_system_config

        cfg = load_system_config()
        if isinstance(cfg, dict):
            return (cfg.get("notification") or {}).get("feishu_webhook")
    except Exception:
        return None
    return None


def _as_card_payload(card: Union[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if isinstance(card, dict):
        # accept full payload or inner card
        if card.get("msg_type") == "interactive" and isinstance(card.get("card"), dict):
            return card
        # if only inner card provided
        if "header" in card and "elements" in card:
            return {"msg_type": "interactive", "card": card}
        return None
    if isinstance(card, str):
        s = card.strip()
        if not s:
            return None
        try:
            import json

            obj = json.loads(s)
            return _as_card_payload(obj)
        except Exception:
            return None
    return None


def tool_send_feishu_card_webhook(
    card: Union[str, Dict[str, Any]],
    webhook_url: Optional[str] = None,
    timeout_seconds: int = 10,
) -> Dict[str, Any]:
    """
    OpenClaw tool: send Feishu interactive card via webhook.

    Args:
        card: card payload (dict) or JSON string. Supports:
          - {"msg_type":"interactive","card":{...}}
          - { ...inner_card... }  (auto-wrapped)
        webhook_url: optional override; default from config notification.feishu_webhook
    """
    payload = _as_card_payload(card)
    if payload is None:
        return {"success": False, "message": "Invalid card payload", "data": None}

    webhook = (webhook_url or "").strip() or _load_webhook_from_config()
    if not webhook:
        return {"success": False, "message": "Missing feishu webhook_url (notification.feishu_webhook)", "data": None}

    try:
        import requests
        try:
            from plugins.utils.proxy_env import without_proxy_env
        except Exception:
            from contextlib import contextmanager

            @contextmanager
            def without_proxy_env(*args, **kwargs):  # type: ignore[misc]
                yield

        with without_proxy_env():
            resp = requests.post(webhook, json=payload, timeout=max(1, int(timeout_seconds)))
        ok_http = 200 <= resp.status_code < 300
        try:
            data = resp.json()
        except Exception:
            data = {"raw": (resp.text or "")[:500]}
        status_code = data.get("StatusCode")
        ok_app = (status_code == 0) if status_code is not None else ok_http
        return {
            "success": bool(ok_app),
            "message": "飞书卡片已发送" if ok_app else "飞书卡片发送失败",
            "http_status": resp.status_code,
            "response": data,
        }
    except Exception as e:
        return {"success": False, "message": f"send feishu card failed: {e}", "data": None}

