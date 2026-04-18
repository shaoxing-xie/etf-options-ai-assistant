"""
Tavily 搜索与通用组合工具（overlay / 定时任务 / 其它 Agent 均可直接 import）。
依赖环境变量 ``TAVILY_API_KEY`` / ``TAVILY_API_KEYS``（多枚逗号分隔，429/432 等自动换 Key）等。

- tavily_post_search：底层 POST，多 Key 回退
- tavily_search：单次 HTTP 检索（内部走 tavily_post_search）
- parse_include_domains / tavily_search_with_include_domain_fallback：域名白名单与失败降级
- tavily_pack_search_result_for_llm / tavily_gather_batch_searches：多路 query 拼成一份 LLM 素材

导入本模块前会尽量加载项目根与 ~/.openclaw/.env（见 src.config_loader 副作用）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


def _ensure_config_env_loaded() -> None:
    """确保已加载 .env（tavily_client 可能被极早 import，早于业务入口）。"""
    try:
        import src.config_loader  # noqa: F401 — 副作用：加载 .env
    except Exception:
        pass


def _resolve_brace_env(s: str) -> str:
    """展开 ${VAR}，与 OpenClaw / llm_structured_extract 行为一致。"""

    def repl(m: re.Match[str]) -> str:
        return os.getenv(m.group(1).strip(), "") or ""

    return re.sub(r"\$\{([^}]+)\}", repl, s or "")


def _tavily_api_key_from_openclaw_json() -> str:
    """
    从 ~/.openclaw/openclaw.json → plugins.entries.tavily-search.config.apiKey 读取。
    在仅配置 OpenClaw 插件、进程未注入 TAVILY_* 环境变量时作为最后兜底（占位符依赖已 load 的 .env）。
    """
    try:
        p = Path.home() / ".openclaw" / "openclaw.json"
        if not p.is_file():
            return ""
        raw = json.loads(p.read_text(encoding="utf-8"))
        plugins = raw.get("plugins") if isinstance(raw, dict) else None
        if not isinstance(plugins, dict):
            return ""
        entries = plugins.get("entries")
        if not isinstance(entries, dict):
            return ""
        tav = entries.get("tavily-search")
        if not isinstance(tav, dict):
            return ""
        cfg = tav.get("config")
        if not isinstance(cfg, dict):
            return ""
        key_raw = cfg.get("apiKey") or cfg.get("api_key")
        if not isinstance(key_raw, str) or not key_raw.strip():
            return ""
        resolved = _resolve_brace_env(key_raw.strip()).strip()
        return resolved
    except Exception:
        return ""


def _tavily_status_try_next_key(status: int) -> bool:
    """额度/限流/临时不可用或单 Key 无效时，尝试列表中的下一枚 Key。"""
    return status in (401, 429, 432, 503)


def collect_tavily_api_keys() -> List[str]:
    """
    返回按优先级排序的 Tavily API Key 列表（去重）。

    配置方式（任选其一，勿把密钥提交到 git）：

    1. **推荐** ``TAVILY_API_KEYS``：逗号或空白分隔多枚，按书写顺序依次尝试（前一枚 429/432 等自动换下一枚）。
    2. 单枚：``TAVILY_API_KEY``，可选 ``TAVILY_API_KEY_2`` … ``TAVILY_API_KEY_9`` 作为备用。
    3. 兼容：``ETF_TAVILY_API_KEY``、``OPENCLAW_TAVILY_API_KEY``、``TAVILY_KEY``。
    4. 最后兜底：``~/.openclaw/openclaw.json`` 插件 tavily-search 的 apiKey。

    若同时设置 ``TAVILY_API_KEYS`` 与单枚变量，**仅当未配置 TAVILY_API_KEYS 时**才合并单枚变量（避免与显式列表重复）。
    """
    _ensure_config_env_loaded()
    keys: List[str] = []
    raw_multi = (os.getenv("TAVILY_API_KEYS") or "").strip()
    if raw_multi:
        for part in re.split(r"[\s,;]+", raw_multi):
            p = part.strip()
            if p and p not in keys:
                keys.append(p)
        return keys

    for k in (
        "TAVILY_API_KEY",
        "ETF_TAVILY_API_KEY",
        "OPENCLAW_TAVILY_API_KEY",
        "TAVILY_KEY",
    ):
        v = (os.getenv(k) or "").strip()
        if v and v not in keys:
            keys.append(v)
    for i in range(2, 10):
        v = (os.getenv(f"TAVILY_API_KEY_{i}") or "").strip()
        if v and v not in keys:
            keys.append(v)
    jk = _tavily_api_key_from_openclaw_json()
    if jk and jk not in keys:
        keys.append(jk)
    return keys


def _collect_api_key() -> str:
    """兼容旧代码：仅返回第一枚可用 Key。"""
    ks = collect_tavily_api_keys()
    return ks[0] if ks else ""


def tavily_post_search(
    body_without_api_key: Dict[str, Any],
    *,
    timeout: float = 25,
) -> Dict[str, Any]:
    """
    调用 Tavily ``/search``，对 ``body_without_api_key`` 注入 ``api_key``。
    多 Key 时在 401/429/432/503 等可恢复错误上自动换下一枚。

    返回 ``{success, data?, message?, http_status?}``；``data`` 为响应 JSON。
    """
    keys = collect_tavily_api_keys()
    if not keys:
        return {
            "success": False,
            "message": "Missing TAVILY_API_KEY（可设置 TAVILY_API_KEYS 多枚或 TAVILY_API_KEY）",
            "data": None,
            "http_status": None,
        }
    try:
        import requests
    except ImportError:
        return {"success": False, "message": "requests_not_installed", "data": None, "http_status": None}

    last_status: Optional[int] = None
    last_msg = ""
    for key in keys:
        body = dict(body_without_api_key)
        body["api_key"] = key
        try:
            resp = requests.post("https://api.tavily.com/search", json=body, timeout=timeout)
        except Exception as e:
            last_msg = str(e)
            last_status = None
            continue
        last_status = resp.status_code
        if resp.ok:
            try:
                return {
                    "success": True,
                    "data": resp.json(),
                    "message": "ok",
                    "http_status": last_status,
                }
            except Exception as e:
                last_msg = str(e)
                continue
        last_msg = f"Tavily HTTP {resp.status_code}"
        try:
            j = resp.json()
            if isinstance(j, dict) and j.get("detail"):
                last_msg = f"{last_msg} {j.get('detail')}"
        except Exception:
            pass
        if not _tavily_status_try_next_key(resp.status_code):
            break
    return {
        "success": False,
        "message": last_msg or "all_tavily_keys_failed",
        "data": None,
        "http_status": last_status,
    }


def build_answer_from_tavily_payload(data: Dict[str, Any], *, max_chars: int = 2800) -> str:
    """
    将 Tavily API JSON 转为可喂给 LLM/展示的合并文本：优先 answer，否则拼接多条 results。
    """
    if not isinstance(data, dict):
        return ""
    parts: List[str] = []
    ans = data.get("answer")
    if isinstance(ans, str) and ans.strip():
        parts.append(ans.strip())
    results = data.get("results") or []
    if isinstance(results, list):
        for res in results[:15]:
            if not isinstance(res, dict):
                continue
            title = (res.get("title") or "").strip()
            body = (res.get("content") or res.get("snippet") or "").strip()
            url = (res.get("url") or "").strip()
            chunk = " | ".join(x for x in (title, body[:900]) if x)
            if chunk:
                parts.append(chunk)
            if url and url not in chunk:
                parts.append(url)
    out = "\n".join(parts).strip()
    return out[:max_chars]


def tavily_effective_answer_text(result: Dict[str, Any], *, max_chars: int = 2500) -> str:
    """工具返回 dict（含 success/raw/answer）上的统一取文入口；优先从 raw 拼出多段摘要。"""
    if not isinstance(result, dict) or not result.get("success"):
        return ""
    raw = result.get("raw")
    if isinstance(raw, dict):
        merged = build_answer_from_tavily_payload(raw, max_chars=max_chars)
        if merged.strip():
            return merged
    return (result.get("answer") or "").strip()[:max_chars]


def tavily_search(
    query: str,
    *,
    max_results: int = 5,
    topic: str = "news",
    days: Optional[int] = 3,
    deep: bool = False,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"success": False, "message": "empty_query", "answer": None, "raw": None}

    body: Dict[str, Any] = {
        "query": q,
        "search_depth": "advanced" if deep else "basic",
        "topic": topic,
        "max_results": max(1, min(int(max_results), 20)),
        "include_answer": True,
        "include_raw_content": False,
    }
    if include_domains:
        body["include_domains"] = [str(d).strip().lstrip("@") for d in include_domains if str(d).strip()][:12]
    if exclude_domains:
        body["exclude_domains"] = [str(d).strip().lstrip("@") for d in exclude_domains if str(d).strip()][
            :12
        ]
    if topic == "news" and days is not None:
        body["days"] = int(days)

    post = tavily_post_search(body, timeout=25)
    if not post.get("success"):
        return {
            "success": False,
            "message": post.get("message")
            or "Missing TAVILY_API_KEY (或 TAVILY_API_KEYS / ETF_TAVILY_API_KEY / OPENCLAW_TAVILY_API_KEY / TAVILY_KEY)；已尝试加载项目 .env 与 ~/.openclaw/.env",
            "answer": None,
            "raw": None,
        }
    data = post.get("data")
    if not isinstance(data, dict):
        return {"success": False, "message": "tavily_invalid_json", "answer": None, "raw": None}
    answer = build_answer_from_tavily_payload(data, max_chars=2400)
    if not answer.strip():
        return {
            "success": False,
            "message": "tavily_empty_answer_and_results",
            "answer": None,
            "raw": data,
        }
    return {
        "success": True,
        "message": "ok",
        "answer": answer.strip()[:2000],
        "raw": data,
    }


# ---------------------------------------------------------------------------
# 通用组合能力：多任务可复用（域名白名单、带降级检索、多路 query 拼接等）
# ---------------------------------------------------------------------------

# 财经/宏观新闻常用域名（Tavily include_domains 上限 12；可按任务覆盖）
DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS: List[str] = [
    "wsj.com",
    "ft.com",
    "reuters.com",
    "bloomberg.com",
    "marketwatch.com",
    "finance.yahoo.com",
    "asia.nikkei.com",
    "data.eastmoney.com",
    "quote.eastmoney.com",
    "finance.eastmoney.com",
]


def parse_include_domains(
    raw: Any,
    *,
    default: Optional[Sequence[str]] = None,
    max_domains: int = 12,
) -> List[str]:
    """
    将 YAML/JSON 中的 include_domains 规范为 host 列表（不含协议）。
    - list：逐项 strip，空列表则退回 default
    - str：逗号分隔
    - 其它 / 空：退回 default（拷贝为 list）
    """
    cap = max(1, min(int(max_domains), 12))
    base = [str(x).strip().lstrip("@") for x in (default or ()) if str(x).strip()][:cap]
    if isinstance(raw, list):
        out = [str(x).strip().lstrip("@") for x in raw if str(x).strip()]
        return (out[:cap] if out else list(base))
    if isinstance(raw, str) and raw.strip():
        return [x.strip().lstrip("@") for x in raw.split(",") if x.strip()][:cap]
    return list(base)


def tavily_search_with_include_domain_fallback(
    query: str,
    *,
    max_results: int = 5,
    topic: str = "news",
    days: Optional[int] = 3,
    deep: bool = False,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    先按 include_domains 检索；失败时去掉域名限制再试一次（提高召回，仍受 Tavily 配额约束）。
    """
    dom = include_domains[:12] if include_domains else None
    r = tavily_search(
        query,
        max_results=max_results,
        topic=topic,
        days=days,
        deep=deep,
        include_domains=dom,
        exclude_domains=exclude_domains,
    )
    if r.get("success"):
        return r
    if dom:
        return tavily_search(
            query,
            max_results=max_results,
            topic=topic,
            days=days,
            deep=deep,
            exclude_domains=exclude_domains,
        )
    return r


def tavily_pack_search_result_for_llm(result: Dict[str, Any], *, max_chars: int = 8000) -> str:
    """
    将单次 tavily_search 成功结果展开为「answer + 逐条结果标题/链接/摘要」，便于喂给下游 LLM。
    """
    if not isinstance(result, dict) or not result.get("success"):
        return ""
    parts: List[str] = []
    ans = (result.get("answer") or "").strip()
    if ans:
        parts.append(ans)
    raw = result.get("raw")
    if isinstance(raw, dict):
        for res in (raw.get("results") or [])[:10]:
            if not isinstance(res, dict):
                continue
            title = res.get("title") or ""
            url = res.get("url") or ""
            body = (res.get("content") or res.get("snippet") or "") or ""
            parts.append(f"\n---\n标题: {title}\n链接: {url}\n{body}\n")
    s = "\n".join(parts).strip()
    return s[:max_chars]


def tavily_gather_batch_searches(
    batches: Sequence[Mapping[str, Any]],
    *,
    include_domains: Optional[List[str]] = None,
    max_results: int = 6,
    topic: str = "news",
    days: int = 2,
    deep: bool = True,
    exclude_domains: Optional[List[str]] = None,
    max_material_chars_per_batch: int = 6000,
    max_digest_chars_per_batch: int = 900,
    max_digest_total: int = 1200,
    material_batch_separator: str = "\n\n",
    digest_batch_separator: str = "\n",
) -> Tuple[str, str]:
    """
    对多组 (query[, header]) 依次调用 Tavily，拼接为一份素材与短 digest；任意任务的多路检索均可复用。

    每个 batch 映射支持键：
    - query（必填）
    - header（可选）：非空时在素材前加 ``==== {header} ====`` 行，便于 LLM 区分检索批次
    """
    mx = max(3, min(int(max_results), 12))
    days_i = int(days) if days is not None else 2
    material_parts: List[str] = []
    digest_parts: List[str] = []

    for b in batches:
        if not isinstance(b, Mapping):
            continue
        q = str(b.get("query") or "").strip()
        if not q:
            continue
        header = str(b.get("header") or "").strip()
        r = tavily_search_with_include_domain_fallback(
            q,
            max_results=mx,
            topic=topic,
            days=days_i,
            deep=bool(deep),
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )
        if not r.get("success"):
            continue
        chunk = tavily_pack_search_result_for_llm(r, max_chars=max_material_chars_per_batch)
        if not chunk.strip():
            continue
        if header:
            material_parts.append(f"==== {header} ====\n{chunk}")
        else:
            material_parts.append(chunk)
        d = tavily_effective_answer_text(r, max_chars=max_digest_chars_per_batch).strip()
        if d:
            digest_parts.append(d)

    material = material_batch_separator.join(material_parts).strip()
    digest = digest_batch_separator.join(digest_parts)[: max(0, int(max_digest_total))]
    return material, digest
