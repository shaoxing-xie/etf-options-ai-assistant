"""
进程内直连 OpenClaw 模型链（不经 Gateway 主模型）。

- llm_json_from_unstructured：非结构化文本 + 抽取提示词 → Chat Completions → 解析为 JSON。
- llm_prose_from_unstructured：素材（Tavily 原文、或上游工具 JSON 序列化事实等）+ 指令 → 简体中文自然语言段落。

模型 ID 与 OpenClaw 一致：`providerId/modelId`（仅在第一个 `/` 处分割 provider）。
主备切换：仅在 HTTP 429、5xx、超时、连接类错误时换下一模型（不对 JSON 解析失败换模型）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.logger_config import get_module_logger
from src.config_loader import load_system_config

logger = get_module_logger(__name__)


def _resolve_env_placeholders_str(s: str) -> str:
    if not s:
        return s
    import os

    def repl(m: re.Match[str]) -> str:
        k = m.group(1).strip()
        return os.getenv(k, "") or ""

    return re.sub(r"\$\{([^}]+)\}", repl, s)


def _load_openclaw_models_block(openclaw_path: Path) -> Dict[str, Any]:
    import yaml

    try:
        raw = openclaw_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("llm_structured_extract: 无法读取 openclaw 配置 %s: %s", openclaw_path, e)
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            data = yaml.safe_load(raw) or {}
        except Exception as e2:
            logger.warning("llm_structured_extract: 解析 openclaw 配置失败: %s", e2)
            return {}
    if not isinstance(data, dict):
        return {}
    models = data.get("models")
    if not isinstance(models, dict):
        return {}
    return models


def resolve_openclaw_chat_model(
    full_model_id: str,
    *,
    openclaw_path: Optional[Path] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    将 `providerId/modelId` 解析为 (base_url, api_key, chat_model_id, error_message)。
    chat_model_id 为传给 chat.completions 的 model 字段（与 OpenClaw 一致，含斜杠）。
    """
    s = (full_model_id or "").strip()
    if "/" not in s:
        return None, None, None, "invalid_model_id_need_provider/model"
    prov, mid = s.split("/", 1)
    prov = prov.strip()
    mid = mid.strip()
    if not prov or not mid:
        return None, None, None, "empty_provider_or_model"

    path = openclaw_path or (Path.home() / ".openclaw" / "openclaw.json")
    path = path.expanduser()
    if not path.is_file():
        return None, None, None, f"openclaw_config_missing:{path}"

    models_block = _load_openclaw_models_block(path)
    providers = models_block.get("providers")
    if not isinstance(providers, dict):
        return None, None, None, "openclaw_models.providers_missing"

    pcfg = providers.get(prov)
    if not isinstance(pcfg, dict):
        return None, None, None, f"unknown_provider:{prov}"

    base_url = str(pcfg.get("baseUrl") or "").strip().rstrip("/")
    api_key_raw = pcfg.get("apiKey")
    api_key = _resolve_env_placeholders_str(str(api_key_raw or "")).strip()
    if not base_url:
        return None, None, None, f"provider_missing_baseUrl:{prov}"
    if not api_key:
        return None, None, None, f"provider_missing_api_key_env:{prov}"

    allowed = {str(m.get("id")) for m in (pcfg.get("models") or []) if isinstance(m, dict)}
    if mid not in allowed:
        # 仍允许调用：部分网关未列全模型也可工作
        logger.debug("llm_structured_extract: model %s not listed under provider %s", mid, prov)

    return base_url, api_key, mid, None


def _strip_json_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t).strip()
    return t


def _parse_json_loose(content: str) -> Any:
    t = _strip_json_fences(content)
    return json.loads(t)


def _is_transport_retryable(exc: BaseException) -> bool:
    """仅传输层：429 / 部分 5xx / 超时 / 连接错误。"""
    try:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            return True
    except ImportError:
        pass
    try:
        import requests

        if isinstance(exc, (requests.Timeout, requests.ConnectTimeout, requests.ConnectionError)):
            return True
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            c = int(exc.response.status_code)
            return c == 429 or c in (500, 502, 503, 504)
    except ImportError:
        pass
    try:
        from openai import APIStatusError, APITimeoutError, APIConnectionError

        if isinstance(exc, (APITimeoutError, APIConnectionError)):
            return True
        if isinstance(exc, APIStatusError):
            c = int(getattr(exc, "status_code", None) or 0)
            return c == 429 or c in (500, 502, 503, 504)
    except ImportError:
        pass
    if isinstance(exc, (TimeoutError, OSError)):
        # OSError 较宽，仅当 errno 为网络类时更稳；此处保守不把全部 OSError 算可重试
        if isinstance(exc, TimeoutError):
            return True
    return False


def _cfg_llm_extract(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if config is None:
        config = load_system_config(use_cache=True)
    block = (config or {}).get("llm_structured_extract") or {}
    return block if isinstance(block, dict) else {}


def _profile_models(cfg_block: Dict[str, Any], profile: str) -> List[str]:
    profiles = cfg_block.get("profiles") or {}
    if not isinstance(profiles, dict):
        return []
    p = profiles.get(profile) or profiles.get("default") or {}
    if not isinstance(p, dict):
        return []
    models = p.get("models") or p.get("model_chain") or []
    if isinstance(models, str):
        return [models.strip()] if models.strip() else []
    if isinstance(models, list):
        return [str(x).strip() for x in models if str(x).strip()]
    return []


def llm_json_from_unstructured(
    raw_text: str,
    extraction_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    profile: str = "default",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    调用 LLM，将非结构化文本转为 JSON 对象（dict 或 list 根）。

    Returns:
        { success, data?, message?, meta: { model_chain, model_used, errors } }
    """
    cfg_block = _cfg_llm_extract(config)
    meta: Dict[str, Any] = {"profile": profile, "model_chain": [], "model_used": None, "errors": []}

    if not cfg_block.get("enabled", False):
        return {"success": False, "message": "llm_structured_extract.disabled", "meta": meta}

    chain = _profile_models(cfg_block, profile)
    if not chain:
        return {"success": False, "message": "llm_structured_extract.no_models_for_profile", "meta": meta}
    meta["model_chain"] = list(chain)

    max_chars = int(cfg_block.get("max_raw_text_chars", 12000))
    rt = (raw_text or "").strip()
    if len(rt) > max_chars:
        rt = rt[:max_chars] + "\n…(truncated)"

    sys_p = (
        system_prompt
        or "你是严谨的金融信息抽取助手。只输出合法 JSON（UTF-8），不要 markdown 围栏，不要解释。"
    )
    user_body = (
        f"{extraction_prompt.strip()}\n\n---\n以下为待处理文本：\n\n{rt}"
    )

    timeout = int(cfg_block.get("timeout_seconds", 90))
    temperature = float(cfg_block.get("temperature", 0.05))
    max_tokens = int(cfg_block.get("max_tokens", 4096))

    oclaw_path_str = cfg_block.get("openclaw_config_path") or "~/.openclaw/openclaw.json"
    oclaw_path = Path(_resolve_env_placeholders_str(str(oclaw_path_str))).expanduser()

    try:
        from openai import OpenAI
    except ImportError as e:
        return {"success": False, "message": f"missing_openai_package:{e}", "meta": meta}

    last_err: Optional[str] = None
    for mid_full in chain:
        base_url, api_key, model_id, err = resolve_openclaw_chat_model(mid_full, openclaw_path=oclaw_path)
        if err:
            meta["errors"].append({"model": mid_full, "phase": "resolve", "error": err})
            last_err = err
            continue
        assert base_url and api_key and model_id
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        kwargs: Dict[str, Any] = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": sys_p},
                {"role": "user", "content": user_body},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if bool(cfg_block.get("use_json_object_response_format", True)):
            kwargs["response_format"] = {"type": "json_object"}

        resp = None
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as e:
            msg_l = str(e).lower()
            if kwargs.get("response_format") and (
                "response_format" in msg_l or "json_object" in msg_l or "400" in msg_l
            ):
                try:
                    kwargs2 = {k: v for k, v in kwargs.items() if k != "response_format"}
                    resp = client.chat.completions.create(**kwargs2)
                except Exception as e2:
                    e = e2
            if resp is None:
                if _is_transport_retryable(e):
                    meta["errors"].append({"model": mid_full, "phase": "request", "error": str(e)[:500]})
                    last_err = str(e)
                    continue
                meta["errors"].append({"model": mid_full, "phase": "request_fatal", "error": str(e)[:500]})
                return {"success": False, "message": str(e)[:500], "meta": meta}

        content = ""
        try:
            content = (resp.choices[0].message.content or "").strip()
            parsed = _parse_json_loose(content)
        except Exception as e:
            # 非传输问题：不换模型重试（按约定）
            meta["errors"].append({"model": mid_full, "phase": "json_parse", "error": str(e)[:500]})
            return {
                "success": False,
                "message": f"json_parse_error:{e}",
                "meta": meta,
                "raw_preview": content[:800] if content else None,
            }

        meta["model_used"] = mid_full
        return {"success": True, "data": parsed, "meta": meta}

    return {"success": False, "message": last_err or "all_models_failed", "meta": meta}


def llm_prose_from_unstructured(
    raw_text: str,
    instructions: str,
    *,
    system_prompt: Optional[str] = None,
    profile: str = "default",
    config: Optional[Dict[str, Any]] = None,
    max_output_chars: int = 2400,
) -> Dict[str, Any]:
    """
    调用 LLM，将 user 消息中的素材（常为 Tavily 检索原文；亦可含上游 tool_* 的 JSON 序列化事实）
    按 instructions 写成**纯中文段落**（非 JSON）。用于外盘综述等：不抽取逐代码指标。

    Returns:
        { success, text?, message?, meta }
    """
    cfg_block = _cfg_llm_extract(config)
    meta: Dict[str, Any] = {"profile": profile, "model_chain": [], "model_used": None, "errors": []}

    if not cfg_block.get("enabled", False):
        return {"success": False, "message": "llm_structured_extract.disabled", "meta": meta}

    chain = _profile_models(cfg_block, profile)
    if not chain:
        return {"success": False, "message": "llm_structured_extract.no_models_for_profile", "meta": meta}
    meta["model_chain"] = list(chain)

    max_chars = int(cfg_block.get("max_raw_text_chars", 12000))
    rt = (raw_text or "").strip()
    if len(rt) > max_chars:
        rt = rt[:max_chars] + "\n…(truncated)"

    sys_p = (
        system_prompt
        or "你是严谨的财经编辑。只输出简体中文正文段落，不要使用 JSON、不要用 markdown 代码围栏、不要编号列表以外的多余格式。"
    )
    user_body = f"{instructions.strip()}\n\n---\n以下为检索与网页素材：\n\n{rt}"

    timeout = int(cfg_block.get("timeout_seconds", 90))
    temperature = float(cfg_block.get("temperature", 0.1))
    max_tokens = int(cfg_block.get("max_tokens", 4096))

    oclaw_path_str = cfg_block.get("openclaw_config_path") or "~/.openclaw/openclaw.json"
    oclaw_path = Path(_resolve_env_placeholders_str(str(oclaw_path_str))).expanduser()

    try:
        from openai import OpenAI
    except ImportError as e:
        return {"success": False, "message": f"missing_openai_package:{e}", "meta": meta}

    last_err: Optional[str] = None
    for mid_full in chain:
        base_url, api_key, model_id, err = resolve_openclaw_chat_model(mid_full, openclaw_path=oclaw_path)
        if err:
            meta["errors"].append({"model": mid_full, "phase": "resolve", "error": err})
            last_err = err
            continue
        assert base_url and api_key and model_id
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        kwargs: Dict[str, Any] = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": sys_p},
                {"role": "user", "content": user_body},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as e:
            if _is_transport_retryable(e):
                meta["errors"].append({"model": mid_full, "phase": "request", "error": str(e)[:500]})
                last_err = str(e)
                continue
            meta["errors"].append({"model": mid_full, "phase": "request_fatal", "error": str(e)[:500]})
            return {"success": False, "message": str(e)[:500], "meta": meta}

        try:
            content = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            meta["errors"].append({"model": mid_full, "phase": "read", "error": str(e)[:500]})
            last_err = str(e)
            continue

        cap = max(400, int(max_output_chars))
        text = content[:cap]
        meta["model_used"] = mid_full
        return {"success": True, "text": text, "meta": meta}

    return {"success": False, "message": last_err or "all_models_failed", "meta": meta}


def tool_llm_json_extract(
    raw_text: str,
    extraction_prompt: str,
    profile: str = "default",
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """OpenClaw / tool_runner 可调用的工具入口。"""
    return llm_json_from_unstructured(
        raw_text,
        extraction_prompt,
        system_prompt=system_prompt,
        profile=profile or "default",
        config=None,
    )
