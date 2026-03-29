"""
发送钉钉自定义机器人（支持 SEC 加签）。

使用方式：
- webhook_url：自定义机器人 webhook（包含 access_token）
- secret：机器人后台“安全模式”SEC 开头的密钥（用于计算 sign）

实现兼容：
- mode="test"：不发网络请求，只做参数校验并返回 skipped
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request
import urllib.error
import re
from typing import Any, Dict, List, Optional


def _get_env(name: str) -> Optional[str]:
    v = os.environ.get(name)
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _build_signed_url(*, webhook_url: str, secret: str) -> str:
    """
    钉钉安全模式加签（timestamp + sign）：
    sign = base64(hmac_sha256(secret, f"{timestamp}\n{secret}"))
    """
    timestamp = str(int(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = base64.b64encode(digest).decode("utf-8")

    parsed = urllib.parse.urlparse(webhook_url)
    q = urllib.parse.parse_qs(parsed.query)
    q["timestamp"] = [timestamp]
    q["sign"] = [sign]
    new_query = urllib.parse.urlencode(q, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def _split_markdown_for_dingtalk(text: str, max_chars: int = 1750) -> List[str]:
    """按二级标题切分，单片超长时按行再切。"""
    t = (text or "").strip()
    if not t:
        return []
    parts = re.split(r"(?m)^(?=## )", t)
    parts = [p.strip() for p in parts if p.strip()]
    out: List[str] = []
    for p in parts:
        if len(p) <= max_chars:
            out.append(p)
            continue
        i = 0
        while i < len(p):
            end = min(i + max_chars, len(p))
            chunk = p[i:end]
            if end < len(p):
                br = chunk.rfind("\n")
                if br > max_chars // 3:
                    chunk = chunk[:br]
                    end = i + br + 1
            chunk = chunk.strip()
            if chunk:
                out.append(chunk)
            if end <= i:
                end = min(i + max_chars, len(p))
            i = end
    return out if out else [t[:max_chars]]


def _dingtalk_single_post(safe_text: str, webhook_url: str, secret: Optional[str]) -> Dict[str, Any]:
    """单条文本发送（含重试）。返回 success / message / response / data.attempt_meta"""
    payload = {"msgtype": "text", "text": {"content": safe_text}}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    opener_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    parsed: Dict[str, Any] = {}
    last_exc: Optional[str] = None
    attempt_meta: List[Dict[str, Any]] = []
    for attempt in range(5):
        try:
            url_attempt = webhook_url
            timestamp_used: Optional[str] = None
            if secret:
                url_attempt = _build_signed_url(webhook_url=webhook_url, secret=secret)
                try:
                    parsed_u = urllib.parse.urlparse(url_attempt)
                    q = urllib.parse.parse_qs(parsed_u.query)
                    timestamp_used = (q.get("timestamp") or [None])[0]
                except Exception:
                    timestamp_used = None
            req_attempt = urllib.request.Request(
                url_attempt,
                data=data,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": "Mozilla/5.0 (compatible; openclaw-dingtalk-bot/1.0)",
                },
                method="POST",
            )
            try:
                with opener_direct.open(req_attempt, timeout=15) as resp:
                    body = resp.read().decode("utf-8") or "{}"
                    try:
                        parsed = json.loads(body)
                    except json.JSONDecodeError:
                        parsed = {"raw": body}
            except Exception:  # noqa: BLE001
                with urllib.request.urlopen(req_attempt, timeout=15) as resp:
                    body = resp.read().decode("utf-8") or "{}"
                    try:
                        parsed = json.loads(body)
                    except json.JSONDecodeError:
                        parsed = {"raw": body}
            last_exc = None
            attempt_meta.append({"attempt": attempt + 1, "timestamp": timestamp_used, "result": "ok"})
            break
        except Exception as e:  # noqa: BLE001
            last_exc = str(e)
            attempt_meta.append({"attempt": attempt + 1, "timestamp": None, "result": "error", "error": last_exc})
            if attempt < 4:
                time.sleep(0.8 * (attempt + 1))
                continue

            parsed = {}
            try:
                import requests

                url_attempt = webhook_url
                timestamp_used = None
                if secret:
                    url_attempt = _build_signed_url(webhook_url=webhook_url, secret=secret)
                    parsed_u = urllib.parse.urlparse(url_attempt)
                    q = urllib.parse.parse_qs(parsed_u.query)
                    timestamp_used = (q.get("timestamp") or [None])[0]
                resp = requests.post(
                    url_attempt,
                    data=json.dumps(payload, ensure_ascii=False),
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                        "User-Agent": "openclaw-dingtalk-bot/1.0",
                    },
                    timeout=15,
                )
                body = resp.text or "{}"
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    parsed = {"raw": body, "http_status": resp.status_code}
                attempt_meta.append({"attempt": attempt + 1, "timestamp": timestamp_used, "result": "ok_via_requests"})
                last_exc = None
            except Exception as e2:  # noqa: BLE001
                attempt_meta.append({"attempt": attempt + 1, "result": "requests_failed", "error": str(e2)})
                parsed = {}

    if last_exc and not parsed:
        return {
            "success": False,
            "message": f"send dingtalk failed after retry: {last_exc}",
            "data": {"attempt_meta": attempt_meta},
        }

    if isinstance(parsed, dict) and parsed.get("errcode") not in (None, 0):
        return {
            "success": False,
            "message": f"dingtalk errcode={parsed.get('errcode')} errmsg={parsed.get('errmsg')}",
            "response": parsed,
            "data": {"attempt_meta": attempt_meta},
        }

    return {"success": True, "response": parsed, "data": {"attempt_meta": attempt_meta}}


def tool_send_dingtalk_message(
    message: str,
    title: Optional[str] = None,
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
    mode: str = "prod",
    split_markdown_sections: bool = False,
    max_chars_per_message: int = 1750,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：发送钉钉文本消息到自定义机器人 webhook。
    split_markdown_sections=True 时按 ## 标题拆多条发送（每条单独加关键词前缀）。
    """
    try:
        safe_title = (title or "").strip()
        safe_msg = (message or "").strip()
        if not safe_msg:
            return {"success": False, "message": "message 不能为空", "data": None}

        # env fallbacks（避免在工具参数里携带敏感信息）
        webhook_url = webhook_url or _get_env("OPENCLAW_DINGTALK_CUSTOM_ROBOT_WEBHOOK_URL")
        secret = secret or _get_env("OPENCLAW_DINGTALK_CUSTOM_ROBOT_SECRET")
        keyword = keyword or _get_env("DINGTALK_KEYWORD") or _get_env("MONITOR_DINGTALK_KEYWORD")
        if not keyword:
            # 尝试复用现有系统配置的 keyword，避免机器人启用了关键词校验但你未显式传入
            cfg_path = Path(os.path.expanduser("~/.openclaw/workspaces/shared/alert_webhook.json"))
            if cfg_path.exists():
                try:
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    keyword = cfg.get("keyword") or cfg.get("dingtalk_keyword")
                except Exception:
                    keyword = None

        if not webhook_url:
            return {"success": False, "message": "缺少钉钉 webhook_url（请通过参数或环境变量配置）", "data": None}

        first_line = safe_msg.split("\n", 1)[0].strip() if safe_msg else ""
        if safe_title and first_line == safe_title.strip():
            main_body = safe_msg
        elif safe_title:
            main_body = f"{safe_title}\n{safe_msg}"
        else:
            main_body = safe_msg

        if str(mode).lower() != "prod":
            if split_markdown_sections:
                parts = _split_markdown_for_dingtalk(main_body, max_chars_per_message)
                return {
                    "success": True,
                    "skipped": True,
                    "message": "dry-run: multipart",
                    "data": {
                        "title": safe_title,
                        "parts": len(parts),
                        "previews": [p[:240] for p in parts[:6]],
                    },
                }
            return {
                "success": True,
                "skipped": True,
                "message": "dry-run: mode != prod",
                "data": {"title": safe_title, "len": len(safe_msg)},
            }

        if split_markdown_sections:
            parts = _split_markdown_for_dingtalk(main_body, max_chars_per_message)
            all_meta: List[Any] = []
            last_resp: Dict[str, Any] = {}
            for idx, chunk in enumerate(parts):
                body = chunk
                if idx > 0:
                    body = f"📄 {idx + 1}/{len(parts)}\n{body}"
                if keyword and keyword not in body:
                    body = f"{keyword}\n{body}"
                r = _dingtalk_single_post(body, webhook_url, secret)
                all_meta.append({"part": idx + 1, **(r.get("data") or {})})
                last_resp = r
                if not r.get("success"):
                    return {
                        "success": False,
                        "message": r.get("message", "multipart failed"),
                        "response": r.get("response"),
                        "data": {"multipart": True, "failed_part": idx + 1, "attempt_meta": all_meta},
                    }
                if idx + 1 < len(parts):
                    time.sleep(0.45)
            return {
                "success": True,
                "response": last_resp.get("response"),
                "data": {"multipart": True, "parts": len(parts), "attempt_meta": all_meta},
            }

        content = main_body
        if keyword and keyword not in content:
            content = f"{keyword}\n{content}"
        safe_text = (
            content if len(content) <= 1800 else (content[:1800] + "\n...(truncated)")
        )
        return _dingtalk_single_post(safe_text, webhook_url, secret)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"send dingtalk failed: {e}", "data": None}

