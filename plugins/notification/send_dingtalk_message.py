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


_INSPECTION_HEADER = "【宽基ETF巡检快报】"
_INSPECTION_STATUS_RE = re.compile(r"(?m)^INSPECTION_RUN_STATUS:\s*(?P<status>.+?)\s*$")
# 默认硬顶（单条字节/字符实践上限）；可被 config notification.dingtalk_max_chars_hard_ceiling 覆盖
DEFAULT_DINGTALK_MAX_CHARS_HARD_CEILING = 20000


def _dingtalk_max_chars_hard_ceiling() -> int:
    """钉钉单条正文硬顶：防止配置误写极大值；默认 20000（高于常见 4k 说法，仍以接口实测为准）。"""
    try:
        from src.config_loader import load_system_config

        raw = (load_system_config(use_cache=True).get("notification") or {}).get(
            "dingtalk_max_chars_hard_ceiling", DEFAULT_DINGTALK_MAX_CHARS_HARD_CEILING
        )
        v = int(raw)
    except Exception:
        v = DEFAULT_DINGTALK_MAX_CHARS_HARD_CEILING
    return max(2000, min(100_000, v))


# 兼容旧单测与外部引用名（= 默认硬顶；实际钳制以 _dingtalk_max_chars_hard_ceiling() 为准）
DINGTALK_CUSTOM_ROBOT_TEXT_SAFE_MAX = DEFAULT_DINGTALK_MAX_CHARS_HARD_CEILING

_INSPECTION_ALLOWED_PREFIXES = (
    _INSPECTION_HEADER,
    "一、当前时段市场快照",
    "二、重点ETF实时位置",
    "三、时段交易提示",
    "四、组合风险快览",
    "风格判定：",
    "当前态势：",
    "主要关注：",
    "操作指令建议：",
    "风险等级：",
    "下次更新：",
    "INSPECTION_RUN_STATUS:",
)
def _normalize_dingtalk_keyword_fragments(keyword: Optional[str]) -> Optional[str]:
    """清理半个书名号并统一为「【关键词】」，避免正文前缀残缺。"""
    if not isinstance(keyword, str):
        return None
    kw = keyword.strip()
    if not kw:
        return None
    # 去掉可能重复/残缺的书名号，再统一包裹
    core = kw.replace("【", "").replace("】", "").strip()
    if not core:
        return None
    return f"【{core}】"


_INSPECTION_ROW_PREFIXES = ("|", "- ")
_INSPECTION_BLOCK_MARKERS = (
    "员:",
    "session",
    "sessionid",
    "sessionkey",
    "agent:",
    "webhook",
    "secret",
    "access_token",
    "tool_call",
    "function=",
    "parameter=",
)
_INSPECTION_SECTION_NORMALIZE = {
    "1、当前时段市场快照": "一、当前时段市场快照",
    "2、重点ETF实时位置": "二、重点ETF实时位置",
    "3、时段交易提示": "三、时段交易提示",
    "4、组合风险快览": "四、组合风险快览",
}


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


def _resolve_max_chars_per_message(explicit: Optional[int]) -> int:
    """
    每条钉钉文本目标长度上限（合并多个 ## 章节直至接近该值）。
    优先工具入参；否则读合并后配置 `notification.dingtalk_max_chars_per_message`（来源：`config/domains/outbound.yaml`；默认 1600）。
    硬顶为 notification.dingtalk_max_chars_hard_ceiling（默认 20000）；硬底 400。
    """
    cap = _dingtalk_max_chars_hard_ceiling()
    if explicit is not None:
        try:
            v = int(explicit)
            if v > 0:
                return min(cap, max(400, v))
        except (TypeError, ValueError):
            pass
    try:
        from src.config_loader import load_system_config

        raw = (load_system_config(use_cache=True).get("notification") or {}).get(
            "dingtalk_max_chars_per_message", 1600
        )
        v = int(raw)
    except Exception:
        v = 1600
    return min(cap, max(400, v))


def _rewind_cut_for_incomplete_number(chunk: str, cut: int, min_keep: int) -> int:
    """
    分片窗口末端若落在「0.」或「0.4」而后续正文是「%…」，说明涨跌幅被腰斩，回退截断点。
    """
    if cut <= min_keep:
        return cut
    head = chunk[:cut].rstrip()
    tail = chunk[cut:] if cut < len(chunk) else ""
    if len(head) <= min_keep:
        return cut
    # …上涨0.  （小数点后无数字）
    m = re.search(r"(\d+)\.$", head)
    if m and m.start() >= min_keep:
        return m.start()
    # …上涨0.4 且下一段以 % 开头（0.4% 被切开）
    m2 = re.search(r"(\d+\.\d+)$", head)
    if m2 and m2.start() >= min_keep and tail.lstrip().startswith("%"):
        return m2.start()
    return cut


def _rewind_cut_for_dangling_conjunction(chunk: str, cut: int, min_keep: int) -> int:
    """
    通用排版回退：若截断后 head 以汉语里常见的连接/转折单字（与、和、及、而）结尾，
    且后续正文以 CJK 汉字起笔，则视为「成分未闭合」，回退到 head 内最近的句读标点（，；：。或 ", "）。
    仅依据字符类别与少量功能字，不对任何行业词、标的或某份报告用语做特判。
    """
    if cut <= min_keep:
        return cut
    head = chunk[:cut].rstrip()
    tail = chunk[cut:] if cut < len(chunk) else ""
    tail_ls = tail.lstrip()
    if not head or not tail_ls:
        return cut
    if not ("\u4e00" <= tail_ls[0] <= "\u9fff"):
        return cut
    if head[-1] not in ("与", "和", "及", "而"):
        return cut
    for sep in ("，", "；", "：", "。"):
        q = head.rfind(sep)
        if q != -1 and q + 1 >= min_keep:
            return q + 1
    q = head.rfind(", ", min_keep, len(head))
    if q != -1:
        return q + 2
    return cut


def _finalize_soft_cut(chunk: str, cut: int, min_keep: int) -> int:
    c = _rewind_cut_for_incomplete_number(chunk, cut, min_keep)
    return _rewind_cut_for_dangling_conjunction(chunk, c, min_keep)


def _soft_break_before(chunk: str, min_keep: int) -> int:
    """
    在 chunk 内选取截断位置（返回第一段的 slice 结束下标，相对 chunk 起点）。
    优先段落/列表行边界，其次句号/逗号/空格；最后经 _finalize_soft_cut 做跨切片通用的
    数字与小数点、汉语功能字边界等归一化，而非针对某段固定正文。
    """
    n = len(chunk)
    if n <= min_keep:
        return n
    # 空段边界
    p2 = chunk.rfind("\n\n", min_keep, n)
    if p2 != -1:
        return _finalize_soft_cut(chunk, p2, min_keep)
    # 下一行像 Markdown 列表/标题/表格
    br_scan = n
    while br_scan > min_keep:
        br_scan = chunk.rfind("\n", min_keep, max(br_scan - 1, min_keep))
        if br_scan == -1:
            break
        nxt = chunk[br_scan + 1 : n].lstrip()
        if nxt.startswith(
            (
                "- ",
                "* ",
                "|",
                "## ",
                "### ",
                "- **",
                "  - ",
                "  * ",
                "`",
            )
        ):
            return _finalize_soft_cut(chunk, br_scan, min_keep)
    # 句末（含标点后缀）
    for sep in ("。", "！", "？", "；"):
        q = chunk.rfind(sep, min_keep, n - 1)
        if q != -1:
            return _finalize_soft_cut(chunk, q + 1, min_keep)
    q = chunk.rfind(". ", min_keep, n)
    if q != -1:
        return _finalize_soft_cut(chunk, q + 2, min_keep)
    # 英文逗号+空格（财经英文叙述）
    q = chunk.rfind(", ", min_keep + 12, n)
    if q != -1:
        return _finalize_soft_cut(chunk, q + 2, min_keep)
    # 百分数后的中文读点（如 0.4%，投资者…）
    for sep in ("%，", "%；", "%。"):
        q = chunk.rfind(sep, min_keep + 8, n)
        if q != -1:
            return _finalize_soft_cut(chunk, q + len(sep), min_keep)
    # 中文逗号（长句无句号时；min_keep+10 略放宽，避免只剩过短尾句）
    q = chunk.rfind("，", min_keep + 10, n)
    if q != -1:
        return _finalize_soft_cut(chunk, q + 1, min_keep)
    br = chunk.rfind("\n", min_keep, n)
    if br != -1:
        return _finalize_soft_cut(chunk, br, min_keep)
    sp = chunk.rfind(" ", min_keep, n)
    if sp != -1:
        return _finalize_soft_cut(chunk, sp, min_keep)
    return _finalize_soft_cut(chunk, n, min_keep)


def _split_oversize_section(section: str, max_chars: int) -> List[str]:
    """单节超过 max_chars 时在软边界切分；非自然断点加简短续接提示。"""
    p = section.strip()
    if not p:
        return []
    if len(p) <= max_chars:
        return [p]
    out: List[str] = []
    i = 0
    min_keep = max(80, max_chars // 3)
    cont_next = False
    while i < len(p):
        end = min(i + max_chars, len(p))
        chunk = p[i:end]
        cut = len(chunk)
        if end < len(p):
            cut = _soft_break_before(chunk, min_keep)
            i_next = i + cut
            while i_next < len(p) and p[i_next] in "\n\r \t":
                i_next += 1
            seg = chunk[:cut].rstrip()
            # 只要后面还有正文（含整窗硬切满 max_chars），都应提示续条，避免「0.4%，投」式半句无交代
            split_early = i_next < len(p)
        else:
            seg = chunk.strip()
            i_next = end
            split_early = False
        if cont_next and seg:
            seg = "（续）" + seg
        if seg and split_early:
            seg = seg + "\n— 未完，见下一条 —"
        if seg:
            out.append(seg)
        cont_next = split_early
        if i_next <= i:
            i_next = min(i + max_chars, len(p))
        i = i_next
    return out if out else [p[:max_chars]]


def _split_markdown_for_dingtalk(text: str, max_chars: int) -> List[str]:
    """先按 Markdown 标题行切成节（``## `` / ``### ``），再**贪心合并**多节到一条，直至接近 max_chars；单节超长再按行切。"""
    t = (text or "").strip()
    if not t:
        return []
    max_chars = min(int(max_chars), _dingtalk_max_chars_hard_ceiling())
    max_chars = max(400, max_chars)
    # 与开盘/晨报一致：正文多为 ### 小节；仅拆 ## 会导致整篇并入一条，分条退化为硬切
    sections = re.split(r"(?m)^(?=(?:###|##) )", t)
    sections = [s.strip() for s in sections if s.strip()]
    if not sections:
        return [t[:max_chars]]
    out: List[str] = []
    buf = ""
    for p in sections:
        sep = "\n\n" if buf else ""
        cand = f"{buf}{sep}{p}" if buf else p
        if len(cand) <= max_chars:
            buf = cand
            continue
        if buf:
            out.append(buf)
            buf = ""
        if len(p) <= max_chars:
            buf = p
        else:
            out.extend(_split_oversize_section(p, max_chars))
    if buf:
        out.append(buf)
    return out if out else [t[:max_chars]]


def _sanitize_inspection_report(text: str) -> Dict[str, Any]:
    """
    巡检快报护栏：
    - 剪掉 header 前的多余前缀
    - 若末行后仍有内容：截断到 INSPECTION_RUN_STATUS 行
    - 若存在“数据不足”：标记 data_degraded
    - 返回 sanitized 文本与建议 run_status（不依赖投递结果）
    """
    raw = (text or "").strip()
    if not raw or _INSPECTION_HEADER not in raw:
        return {"is_inspection": False, "sanitized": raw, "suggested_status": None}

    start = raw.find(_INSPECTION_HEADER)
    body = raw[start:].strip()

    m = None
    for m in _INSPECTION_STATUS_RE.finditer(body):
        pass
    if m:
        end_idx = m.end()
        body = body[:end_idx].rstrip()

    cleaned_lines: List[str] = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            cleaned_lines.append("")
            continue
        for bad, good in _INSPECTION_SECTION_NORMALIZE.items():
            if s.startswith(bad):
                suffix = s[len(bad):]
                s = good + suffix
                break
        low = s.lower()
        if any(mark in low for mark in _INSPECTION_BLOCK_MARKERS):
            continue
        # 去掉明显未替换占位符/模板残片
        if "{" in s or "}" in s:
            continue
        if s.startswith(_INSPECTION_ALLOWED_PREFIXES) or s.startswith(_INSPECTION_ROW_PREFIXES):
            cleaned_lines.append(s)
            continue
        # 章节内的普通说明行允许少量白名单
        if (
            s.startswith("当前")
            or s.startswith("主要")
            or s.startswith("操作")
            or s.startswith("风险")
            or s.startswith("下次")
        ):
            cleaned_lines.append(s)
            continue
        # 其余杂质行一律删除，避免内部元信息或乱码对外泄漏
        continue

    body = "\n".join(cleaned_lines).strip()
    if "风格判定：" not in body:
        body = body.replace("二、重点ETF实时位置", "风格判定：数据不足\n\n二、重点ETF实时位置", 1)
    data_degraded = "数据不足" in body
    suggested = "data_source_degraded" if data_degraded else "ok"

    if _INSPECTION_STATUS_RE.search(body):
        body = _INSPECTION_STATUS_RE.sub(f"INSPECTION_RUN_STATUS: {suggested}", body, count=1)

    return {
        "is_inspection": True,
        "sanitized": body,
        "suggested_status": suggested,
        "data_degraded": data_degraded,
    }


def _dingtalk_single_post(safe_text: str, webhook_url: str, secret: Optional[str]) -> Dict[str, Any]:
    """单条文本发送（含重试）。返回 success / message / response / data.attempt_meta"""
    payload = {"msgtype": "text", "text": {"content": safe_text}}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    opener_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    parsed: Dict[str, Any] = {}
    last_exc: Optional[str] = None
    attempt_meta: List[Dict[str, Any]] = []
    # 契约：失败最多重试 1 次（共 2 次尝试）
    for attempt in range(2):
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
                    parsed.setdefault("http_status", getattr(resp, "status", None))
            except urllib.error.HTTPError as he:
                # urllib 在非 2xx 时抛 HTTPError，但 body 仍可读
                try:
                    body = he.read().decode("utf-8") or "{}"
                except Exception:  # noqa: BLE001
                    body = "{}"
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    parsed = {"raw": body}
                parsed["http_status"] = getattr(he, "code", None)
            except Exception:  # noqa: BLE001
                with urllib.request.urlopen(req_attempt, timeout=15) as resp:
                    body = resp.read().decode("utf-8") or "{}"
                    try:
                        parsed = json.loads(body)
                    except json.JSONDecodeError:
                        parsed = {"raw": body}
                    parsed.setdefault("http_status", getattr(resp, "status", None))
            last_exc = None
            attempt_meta.append({"attempt": attempt + 1, "timestamp": timestamp_used, "result": "ok"})
            break
        except Exception as e:  # noqa: BLE001
            last_exc = str(e)
            attempt_meta.append({"attempt": attempt + 1, "timestamp": None, "result": "error", "error": last_exc})
            if attempt < 1:
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
    message: Optional[str] = None,
    title: Optional[str] = None,
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
    mode: str = "prod",
    split_markdown_sections: bool = False,
    max_chars_per_message: Optional[int] = None,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：发送钉钉文本消息到自定义机器人 webhook。

    - 分条时：多个 ``## `` / ``### `` 章节会**合并**进同一条，直至接近单条字数上限（减少刷屏）。
    - ``max_chars_per_message``：显式传入则优先；否则读合并后配置 →
      ``notification.dingtalk_max_chars_per_message``（来源：`config/domains/outbound.yaml`；默认 1600）；硬顶见
      ``dingtalk_max_chars_hard_ceiling``（默认 20000）。
    - 未开启显式分条（``split_markdown_sections=False``）时：若全文超过 **有效**单条上限，**自动**走分条发送，
      避免单条被硬截断为 ``...(truncated)``。
    """
    try:
        safe_title = (title or "").strip()
        safe_msg = (message or "").strip()
        # LLM 有时会错误地以空参数调用该工具（arguments={}）。
        # 为了避免 cron hard_fail_send 直接终止，这里把“缺失正文”降级为 skipped。
        if not safe_msg:
            return {
                "success": True,
                "skipped": True,
                "message": "skipped: missing dingtalk message",
                "data": {"title": safe_title},
            }

        guard = _sanitize_inspection_report(safe_msg)
        if guard.get("is_inspection"):
            safe_msg = str(guard.get("sanitized") or "").strip()

        # env fallbacks（避免在工具参数里携带敏感信息）
        webhook_url = webhook_url or _get_env("OPENCLAW_DINGTALK_CUSTOM_ROBOT_WEBHOOK_URL")
        secret = secret or _get_env("OPENCLAW_DINGTALK_CUSTOM_ROBOT_SECRET")
        keyword = _normalize_dingtalk_keyword_fragments(
            keyword or _get_env("DINGTALK_KEYWORD") or _get_env("MONITOR_DINGTALK_KEYWORD")
        )
        if not keyword:
            # 尝试复用现有系统配置的 keyword，避免机器人启用了关键词校验但你未显式传入
            cfg_path = Path(os.path.expanduser("~/.openclaw/workspaces/shared/alert_webhook.json"))
            if cfg_path.exists():
                try:
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    keyword = _normalize_dingtalk_keyword_fragments(
                        cfg.get("keyword") or cfg.get("dingtalk_keyword")
                    )
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

        effective_mc = _resolve_max_chars_per_message(max_chars_per_message)
        use_multipart = bool(split_markdown_sections) or len(main_body) > effective_mc
        auto_split = bool(not split_markdown_sections and use_multipart)

        if str(mode).lower() != "prod":
            if use_multipart:
                parts = _split_markdown_for_dingtalk(main_body, effective_mc)
                part_lengths = [len(p) for p in parts]
                return {
                    "success": True,
                    "skipped": True,
                    "message": "dry-run: multipart",
                    "data": {
                        "title": safe_title,
                        "parts": len(parts),
                        "part_lengths": part_lengths,
                        "previews": [p[:240] for p in parts[:6]],
                        "guard": guard,
                        "auto_split": auto_split,
                        "split_markdown_sections": bool(split_markdown_sections),
                        "max_chars_per_message": effective_mc,
                    },
                }
            return {
                "success": True,
                "skipped": True,
                "message": "dry-run: mode != prod",
                "data": {
                    "title": safe_title,
                    "parts": 1,
                    "part_lengths": [len(main_body)],
                    "len": len(safe_msg),
                    "guard": guard,
                },
            }

        if use_multipart:
            parts = _split_markdown_for_dingtalk(main_body, effective_mc)
            part_lengths = [len(p) for p in parts]
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
                        "delivery": {
                            "channel": "dingtalk",
                            "ok": False,
                            "status": "dingtalk_fail",
                            "attempts": len(all_meta),
                        },
                        "data": {
                            "multipart": True,
                            "auto_split": auto_split,
                            "parts": len(parts),
                            "part_lengths": part_lengths,
                            "failed_part": idx + 1,
                            "attempt_meta": all_meta,
                            "guard": guard,
                        },
                    }
                if idx + 1 < len(parts):
                    time.sleep(0.45)
            return {
                "success": True,
                "response": last_resp.get("response"),
                "delivery": {
                    "channel": "dingtalk",
                    "ok": True,
                    "status": str(guard.get("suggested_status") or "ok"),
                    "attempts": len(all_meta),
                },
                "data": {
                    "multipart": True,
                    "parts": len(parts),
                    "part_lengths": part_lengths,
                    "auto_split": auto_split,
                    "max_chars_per_message": effective_mc,
                    "attempt_meta": all_meta,
                    "guard": guard,
                },
            }

        content = main_body
        if keyword and keyword not in content:
            content = f"{keyword}\n{content}"
        safe_text = (
            content
            if len(content) <= effective_mc
            else (content[:effective_mc] + "\n...(truncated)")
        )
        was_truncated = len(content) > effective_mc
        r = _dingtalk_single_post(safe_text, webhook_url, secret)
        ok = bool(r.get("success"))
        status = str(guard.get("suggested_status") or "ok") if ok else "dingtalk_fail"
        return {
            **r,
            "delivery": {
                "channel": "dingtalk",
                "ok": ok,
                "status": status,
                "attempts": len((r.get("data") or {}).get("attempt_meta") or []),
                "errcode": (r.get("response") or {}).get("errcode") if isinstance(r.get("response"), dict) else None,
                "errmsg": (r.get("response") or {}).get("errmsg") if isinstance(r.get("response"), dict) else None,
                "http_status": (r.get("response") or {}).get("http_status") if isinstance(r.get("response"), dict) else None,
            },
            "data": {
                **(r.get("data") or {}),
                "parts": 1,
                "part_lengths": [len(safe_text)],
                "truncated": was_truncated,
                "guard": guard,
            },
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"send dingtalk failed: {e}", "data": None}

