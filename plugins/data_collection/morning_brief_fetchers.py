#!/usr/bin/env python3
"""
盘前晨报辅助采集：政策要闻、大宗商品 spot、A50/金龙检索降级、公告速览。
依赖 TAVILY_API_KEY；失败返回结构化降级信息，不抛异常。
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import pytz


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _cache_dir() -> Path:
    d = _project_root() / "data" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _today_str() -> str:
    return datetime.now(pytz.timezone("Asia/Shanghai")).strftime("%Y%m%d")


_tavily_env_loaded = False


def _ensure_tavily_env() -> None:
    """在未经过 tool_runner 时，仍尝试从项目根 / ~/.openclaw/.env 加载 TAVILY 等变量。"""
    global _tavily_env_loaded
    if _tavily_env_loaded:
        return
    _tavily_env_loaded = True
    _pl = Path(__file__).resolve().parents[1]
    if str(_pl) not in sys.path:
        sys.path.insert(0, str(_pl))
    try:
        from utils.env_loader import load_env_file
    except ImportError:
        return
    root = _project_root()
    load_env_file(root / ".env", override=False)
    load_env_file(Path.home() / ".openclaw" / ".env", override=False)


def _tavily_api_key() -> str:
    _ensure_tavily_env()
    for name in (
        "TAVILY_API_KEY",
        "OPENCLAW_TAVILY_API_KEY",
        "TAVILY_KEY",
    ):
        v = (os.getenv(name) or "").strip()
        if v:
            return v
    return ""


def _tavily_search(
    query: str,
    *,
    n: int = 5,
    topic: str = "news",
    days: int = 3,
    deep: bool = False,
) -> Dict[str, Any]:
    api_key = _tavily_api_key()
    if not api_key:
        return {
            "success": False,
            "message": "Missing TAVILY_API_KEY（可在 ~/.openclaw/.env 或项目根 .env 设置 TAVILY_API_KEY）",
            "data": None,
        }
    try:
        import requests

        body: Dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced" if deep else "basic",
            "topic": topic,
            "max_results": max(1, min(int(n), 20)),
            "include_answer": True,
            "include_raw_content": False,
        }
        if topic == "news" and days:
            body["days"] = int(days)
        resp = requests.post("https://api.tavily.com/search", json=body, timeout=18)
        if not resp.ok:
            return {
                "success": False,
                "message": f"Tavily HTTP {resp.status_code}",
                "data": None,
            }
        return {"success": True, "data": resp.json()}
    except Exception as e:
        return {"success": False, "message": str(e), "data": None}


def _policy_relevant(item: Dict[str, Any]) -> bool:
    """宏观/监管类噪音过滤（标题+摘要）。"""
    blob = (
        f"{item.get('title') or ''} {item.get('snippet') or ''}"
    ).lower()
    keys = (
        "监管",
        "证监会",
        "央行",
        "国务院",
        "降准",
        "降息",
        "宏观",
        "财政部",
        "商务部",
        "发改委",
        "外汇",
        "mlf",
        "lpr",
        "政策",
        "条例",
        "新规",
    )
    return any(k in blob for k in keys)


def _compact_results(
    raw: Any, limit: int, *, content_max: int = 400
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for r in raw[:limit]:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "").strip()
        url = str(r.get("url") or "").strip()
        content = str(r.get("content") or "").strip()
        if not title or not url:
            continue
        out.append(
            {
                "title": title[:200],
                "url": url[:500],
                "snippet": content[:content_max] if content else None,
                "source_type": "search",
            }
        )
    return out


def tool_fetch_policy_news(
    max_items: int = 5,
    use_cache: bool = True,
    disable_network: bool = False,
) -> Dict[str, Any]:
    """
    宏观/监管政策要闻（Tavily + 可选本地缓存）。
    """
    cache_path = _cache_dir() / f"policy_news_{_today_str()}.json"
    if use_cache and cache_path.exists() and not disable_network:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("items"):
                return {"success": True, "message": "cache_hit", "data": cached}
        except Exception:
            pass

    if disable_network:
        return {
            "success": False,
            "message": "network_disabled",
            "data": {"items": [], "as_of": _today_str()},
        }

    q = (
        "中国 宏观政策 OR 监管 证监会 OR 央行 降准 降息 "
        "site:cscs.com OR site:cs.com.cn OR site:stcn.com OR site:cninfo.com.cn"
    )
    tav = _tavily_search(q, n=max(5, max_items + 2), topic="news", days=2, deep=False)
    if not tav.get("success"):
        return {
            "success": False,
            "message": tav.get("message") or "tavily_failed",
            "data": {"items": [], "as_of": _today_str()},
        }
    data = tav.get("data") or {}
    results = data.get("results") or []
    answer = data.get("answer")
    raw_items = _compact_results(results, max(1, min(max_items + 4, 12)))
    items = [it for it in raw_items if _policy_relevant(it)]
    if not items:
        items = raw_items[:max_items]
    items = items[:max_items]
    for it in items:
        it["category"] = "policy"

    payload = {
        "as_of": datetime.now(pytz.timezone("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
        "brief_answer": (str(answer).strip()[:500] if answer else None),
        "items": items,
        "numeric_unverified": True,
        "source_type": "search",
    }
    try:
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass

    return {"success": True, "message": "ok", "data": payload}


def _macro_tavily_fallback() -> Dict[str, Any]:
    """yfinance 全失败时用 Tavily 一条聚合摘要（numeric_unverified）。"""
    q = "WTI crude oil COMEX gold copper futures percent change overnight 彭博 路透"
    tav = _tavily_search(q, n=5, topic="news", days=1, deep=False)
    if not tav.get("success"):
        return {
            "success": False,
            "message": tav.get("message") or "tavily_failed",
            "data": {"items": [], "source": "tavily"},
        }
    data = tav.get("data") or {}
    answer = data.get("answer")
    rows = _compact_results(data.get("results") or [], 5)
    items: List[Dict[str, Any]] = []
    if answer:
        items.append(
            {
                "code": "macro_digest",
                "name": "大宗检索提要",
                "change_pct": None,
                "digest": str(answer).strip()[:500],
                "source": "tavily",
                "numeric_unverified": True,
            }
        )
    for r in rows[:4]:
        items.append(
            {
                "code": "news",
                "name": (r.get("title") or "")[:80],
                "change_pct": None,
                "digest": (r.get("snippet") or "")[:300],
                "url": r.get("url"),
                "source": "tavily",
                "numeric_unverified": True,
            }
        )
    if not items:
        return {
            "success": False,
            "message": "tavily_empty",
            "data": {"items": [], "source": "tavily"},
        }
    return {
        "success": True,
        "message": "tavily_fallback",
        "data": {"items": items, "source": "tavily", "numeric_unverified": True},
    }


def tool_fetch_macro_commodities(
    disable_network: bool = False,
) -> Dict[str, Any]:
    """
    原油 / 黄金 / 铜 涨跌幅：优先 yfinance；无数据或部分失败时可尝试 Tavily 摘要降级。
    """
    if disable_network:
        return {
            "success": False,
            "message": "network_disabled",
            "data": {"items": [], "source": None},
        }
    symbols = [
        ("CL=F", "WTI原油"),
        ("GC=F", "COMEX黄金"),
        ("HG=F", "COMEX铜"),
    ]
    items: List[Dict[str, Any]] = []
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        return {
            "success": False,
            "message": "yfinance_not_installed",
            "data": {
                "items": [],
                "hint": "可改用 tool_fetch_overnight_futures_digest 或 tavily 摘要",
            },
        }

    for sym, name in symbols:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="5d")
            if hist is None or hist.empty:
                continue
            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
            chg_pct = (price - prev) / prev * 100 if prev else None
            items.append(
                {
                    "code": sym,
                    "name": name,
                    "change_pct": round(chg_pct, 4) if chg_pct is not None else None,
                    "source": "yfinance",
                }
            )
        except Exception:
            continue

    if not items:
        fb = _macro_tavily_fallback()
        if fb.get("success"):
            fb["message"] = "yfinance_empty_tavily_fallback"
        return fb
    if len(items) < 3:
        fb = _macro_tavily_fallback()
        if fb.get("success"):
            merge = list(items) + (fb.get("data") or {}).get("items", [])
            return {
                "success": True,
                "message": "yfinance_partial_plus_tavily",
                "data": {
                    "items": merge[:8],
                    "source": "yfinance+tavily",
                    "numeric_unverified": True,
                },
            }
    return {"success": True, "message": "ok", "data": {"items": items, "source": "yfinance"}}


def tool_conditional_overnight_futures_digest(
    overnight_overlay_degraded: bool = False,
    before_open_analysis: Optional[Dict[str, Any]] = None,
    disable_network: bool = False,
) -> Dict[str, Any]:
    """
    当盘前分析 `overnight_overlay_degraded==true`（或显式传 True）时拉取 A50/金龙 tavily 摘要，否则跳过以减少限流。
    """
    need = bool(overnight_overlay_degraded)
    if before_open_analysis and isinstance(before_open_analysis, dict):
        need = need or bool(before_open_analysis.get("overnight_overlay_degraded"))
    if not need:
        return {
            "success": True,
            "message": "skipped_overnight_numeric_ok",
            "data": None,
        }
    return tool_fetch_overnight_futures_digest(disable_network=disable_network)


def tool_fetch_overnight_futures_digest(
    disable_network: bool = False,
) -> Dict[str, Any]:
    """
    A50 期指 + 纳斯达克中国金龙 隔夜/夜盘定性摘要（numeric_unverified）。
    主源失败时由工作流调用本工具，不写入可回测涨跌幅。
    """
    if disable_network:
        return {
            "success": False,
            "message": "network_disabled",
            "data": None,
        }
    out: Dict[str, Any] = {
        "as_of": datetime.now(pytz.timezone("Asia/Shanghai")).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "a50_digest": None,
        "hxc_digest": None,
        "evidence_urls": [],
        "source_type": "search_fallback",
        "numeric_unverified": True,
    }
    q1 = "富时中国A50指数期货 夜盘 涨跌幅 隔夜"
    r1 = _tavily_search(q1, n=3, topic="news", days=1, deep=False)
    if r1.get("success"):
        d = r1.get("data") or {}
        ans = d.get("answer")
        if ans:
            out["a50_digest"] = str(ans).strip()[:400]
        for it in _compact_results(d.get("results") or [], 3):
            out["evidence_urls"].append(it["url"])

    q2 = "纳斯达克中国金龙指数 HXC 隔夜 涨跌"
    r2 = _tavily_search(q2, n=3, topic="news", days=1, deep=False)
    if r2.get("success"):
        d2 = r2.get("data") or {}
        ans2 = d2.get("answer")
        if ans2:
            out["hxc_digest"] = str(ans2).strip()[:400]
        for it in _compact_results(d2.get("results") or [], 3):
            if it["url"] not in out["evidence_urls"]:
                out["evidence_urls"].append(it["url"])

    ok = bool(out["a50_digest"] or out["hxc_digest"])
    return {
        "success": ok,
        "message": "ok" if ok else "no_digest",
        "data": out if ok else out,
    }


def tool_fetch_announcement_digest(
    max_items: int = 5,
    disable_network: bool = False,
) -> Dict[str, Any]:
    """重大事项 / 业绩预告 / 增减持 — Tavily 摘要。"""
    if disable_network:
        return {
            "success": False,
            "message": "network_disabled",
            "data": {"items": []},
        }
    q = (
        "A股 重大公告 业绩预告 增持 减持 "
        "site:cninfo.com.cn OR site:eastmoney.com"
    )
    tav = _tavily_search(q, n=max_items + 3, topic="news", days=1, deep=False)
    if not tav.get("success"):
        return {
            "success": False,
            "message": tav.get("message") or "tavily_failed",
            "data": {"items": []},
        }
    data = tav.get("data") or {}
    items = _compact_results(data.get("results") or [], max(1, min(max_items, 8)))
    kws = ("预告", "业绩", "增持", "减持", "重大", "重组", "停牌", "风险")
    filtered = [
        it
        for it in items
        if any(k in it.get("title", "") + (it.get("snippet") or "") for k in kws)
    ]
    if not filtered:
        filtered = items[:max_items]
    for it in filtered:
        it["category"] = "announcement"
    return {
        "success": True,
        "message": "ok",
        "data": {
            "as_of": datetime.now(pytz.timezone("Asia/Shanghai")).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "items": filtered[:max_items],
            "numeric_unverified": True,
            "source_type": "search",
        },
    }


_INDUSTRY_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _industry_authority_url(item: Dict[str, Any]) -> bool:
    """行业要闻工具：仅证券时报/中证/财联社/东财正文域，与检索 site: 白名单一致。"""
    url = (item.get("url") or "").lower()
    if not url.startswith("http"):
        return False
    if "caifuhao.eastmoney.com" in url or "guba.eastmoney.com" in url:
        return False
    return any(
        h in url
        for h in (
            "stcn.com",
            "cs.com.cn",
            "cls.cn",
            "finance.eastmoney.com",
            "stock.eastmoney.com",
        )
    )


def _industry_cn_content(item: Dict[str, Any]) -> bool:
    """正文或标题需含中文，或为国内主流财经域名（避免 Tavily 混入美股/英文页）。"""
    blob = f"{item.get('title') or ''} {item.get('snippet') or ''}"
    if _INDUSTRY_CJK_RE.search(blob):
        return True
    url = (item.get("url") or "").lower()
    allowed = (
        "stcn.com",
        "cs.com.cn",
        "yicai.com",
        "cls.cn",
        "eastmoney.com",
        "hexun.com",
        "10jqka.com.cn",
        "wallstreetcn.com",
        "caixin.com",
        "qq.com",
        "sina.com.cn",
        "163.com",
        "ifeng.com",
        "jrj.com.cn",
    )
    return any(a in url for a in allowed)


def _industry_relevant(item: Dict[str, Any]) -> bool:
    if not _industry_cn_content(item):
        return False
    blob = f"{item.get('title') or ''} {item.get('snippet') or ''}"
    keys = (
        "板块",
        "行业",
        "景气",
        "轮动",
        "配置",
        "公募",
        "外资",
        "新能源",
        "医药",
        "科技",
        "半导体",
        "券商",
        "有色",
        "煤炭",
        "钢铁",
        "电力",
        "光伏",
        "锂电",
        "汽车",
        "消费",
        "制造",
        "算力",
    )
    return any(k in blob for k in keys)


def _industry_bad_listing_url(url: str) -> bool:
    """剔除中证网/证券时报等频道目录页（非单篇 .html 正文）。"""
    if not url or not url.startswith("http"):
        return True
    ul = url.lower()
    if "cs.com.cn" in ul:
        if ".html" in ul:
            return False
        if re.search(r"/t20\d{6}_", url):
            return False
        path = urlparse(url).path.strip("/")
        segs = [s for s in path.split("/") if s]
        if len(segs) <= 1:
            return True
    if "stcn.com" in ul:
        if "/article/detail/" in url and ".html" in ul:
            return False
        if ".html" in ul:
            return False
        return True
    return False


def _industry_noise_hard(item: Dict[str, Any]) -> bool:
    """
    规则粗筛：域名/目录页/星翼/明显盘面稿/盘中宝等，必须剔除（不交给 LLM）。
    不含长串标题党短语、十大券商汇编等——留给 LLM 或 strict 路径处理。
    """
    url = (item.get("url") or "").lower()
    raw_url = item.get("url") or ""
    title = item.get("title") or ""
    snip = item.get("snippet") or ""
    blob = f"{title} {snip}"
    if _industry_bad_listing_url(raw_url):
        return True
    # 低质域名（社区帖、自媒体号）
    bad_hosts = (
        "caifuhao.eastmoney.com",
        "guba.eastmoney.com",
        "toutiao.com",
    )
    if any(h in url for h in bad_hosts):
        return True
    # 海外财经站（与 A 股行业要闻无关）
    foreign_hosts = (
        "gurufocus.com",
        "benzinga.com",
        "seekingalpha.com",
        "fool.com",
        "marketwatch.com",
        "investing.com",
        "finviz.com",
        "bloomberg.com",
        "reuters.com",
    )
    if any(h in url for h in foreign_hosts):
        return True
    if "星翼大模型" in f"{title}{snip}":
        return True
    if "/qs/" in url or url.rstrip("/").endswith("/qs"):
        return True
    ts = title.strip()
    if ts.startswith("收评：") or ts.startswith("收评:"):
        return True
    if (
        "焦点复盘" in title
        or "【焦点复盘】" in title
        or "收盘复盘" in title
        or "盘面复盘" in title
    ):
        return True
    if "复盘】" in title and ("三大指数" in title or "沪指" in title[:20]):
        return True
    if "【盘中宝】" in title or "《盘中宝》" in title:
        return True
    tl = title.lower()
    if "盘中发文" in title and "涨停" in title:
        return True
    if "大牛股" in title and ("20cm" in tl or "涨停" in title):
        return True
    if not _industry_authority_url(item):
        return True
    return False


def _industry_noise_soft(item: Dict[str, Any]) -> bool:
    """细规则：标题党、十大券商周报体、站点导航等（strict 路径；粗筛可跳过）。"""
    title = item.get("title") or ""
    snip = item.get("snippet") or ""
    blob = f"{title} {snip}"
    # 标题党 / 复盘水帖 / 八卦向（非行业研究）
    noise_phrases = (
        "涨停潮",
        "刚刚，",
        "突发！",
        "炒股日记",
        "复盘记录",
        "强势机会",
        "股市怎么看",
        "掀涨停",
        "掀“涨停",
        "马云",
        "喝可乐",
        "轰下台",
        "兄弟姐妹",
        "下周a股",
        "开盘时间",
        "十大券商最新研判",
        "教育名师",
        "最新通报",
        "长假",
        "持币",
        "持股",
        "日历效应",
        "国庆",
        "中秋",
        "本周十大券商",
        "券商策略来了",
        "换挡提速",
        "十大券商策略：",
    )
    if any(p in blob.lower() for p in noise_phrases):
        return True
    # 标题即「十大券商策略」周报汇编（财联社等），非单行业深度
    tl = title.strip()
    if tl.startswith("十大券商策略") or "丨十大券商策略" in tl:
        return True
    if blob.count("$") >= 2:
        return True
    if "致力于为用户提供实时专业财经" in snip or "覆盖宏观经济,金融市场" in snip:
        return True
    if " - " in title and len(title.strip()) <= 18 and title.endswith("网"):
        return True
    if "券商晨会精华" in title or "晨会精华" in title:
        return True
    if re.search(r"\d{4}年.{0,40}调研路线", title):
        return True
    return False


def _industry_noise(item: Dict[str, Any]) -> bool:
    """剔除东财财富号/股吧风、标题党；保留研究向行业信息（= 硬规则 + 软规则）。"""
    return _industry_noise_hard(item) or _industry_noise_soft(item)


def _industry_stale_or_clickbait_year(item: Dict[str, Any]) -> bool:
    """标题强绑定旧年份（如 2023 新财富）且非当年综述时降权过滤。"""
    title = item.get("title") or ""
    if "2023" in title and "2024" not in title and "2025" not in title and "2026" not in title:
        if "新财富" in title or "买什么" in title:
            return True
    return False


def _parse_tavily_published_to_shanghai(raw: Any) -> Optional[datetime]:
    """Tavily 结果里的 published_date（多为 ISO8601）→ 上海时区 datetime。"""
    if raw is None:
        return None
    tz = pytz.timezone("Asia/Shanghai")
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=pytz.UTC).astimezone(tz)
        except (ValueError, OSError):
            return None
    t = str(raw).strip()
    if not t:
        return None
    try:
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = tz.localize(dt)
        else:
            dt = dt.astimezone(tz)
        return dt
    except ValueError:
        return None


def _industry_attach_tavily_published(
    items: List[Dict[str, Any]], raw_results: Any
) -> None:
    """把 Tavily 原始条目的 published_date 挂到 compact 后的 item 上。"""
    if not isinstance(raw_results, list):
        return
    by_url: Dict[str, Any] = {}
    for r in raw_results:
        if not isinstance(r, dict):
            continue
        u = str(r.get("url") or "").strip()
        if u and r.get("published_date"):
            by_url[u] = r["published_date"]
    for it in items:
        u = it.get("url") or ""
        if u in by_url:
            it["published_date"] = by_url[u]


def _industry_extract_pub_date(item: Dict[str, Any]) -> Optional[datetime]:
    """
    从 Tavily published_date、东财 URL、摘要/作者行等解析发稿日（上海）。
    多个来源并存时取**最早**日期，避免「抓取时间很新、正文其实是旧稿」（如盘中宝摘要内的 2025.11.13）。
    """
    tz = pytz.timezone("Asia/Shanghai")
    snip = item.get("snippet") or ""
    url = item.get("url") or ""
    title = item.get("title") or ""
    head = f"{title}\n{snip}"[:2000]
    cands: List[datetime] = []

    def _loc(y: str, mo: str, d: str) -> Optional[datetime]:
        try:
            return tz.localize(datetime(int(y), int(mo), int(d)))
        except (ValueError, TypeError):
            return None

    def _add(d: Optional[datetime]) -> None:
        if d:
            cands.append(d)

    pd = item.get("published_date")
    tav_d = _parse_tavily_published_to_shanghai(pd) if pd else None

    m = re.search(
        r"(?:finance|stock)\.eastmoney\.com/a/(\d{4})(\d{2})(\d{2})\d+\.html",
        url,
        re.I,
    )
    if m:
        d = _loc(m.group(1), m.group(2), m.group(3))
        if d:
            return d

    m = re.search(
        r"作者：[^\d\n]{1,40}(\d{4}-\d{2}-\d{2})\s+\d{1,2}:\d{2}",
        head,
    )
    if m:
        parts = m.group(1).split("-")
        _add(_loc(parts[0], parts[1], parts[2]))
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})\s+\d{1,2}:\d{2}", head)
    if m:
        _add(_loc(m.group(1), m.group(2), m.group(3)))
    # 财联社电头：2025.11.13 09:02 / 全角冒号
    m = re.search(
        r"(20\d{2})\.(\d{1,2})\.(\d{1,2})\s+\d{1,2}[:：]\d{2}",
        (snip or "")[:2500],
    )
    if m:
        _add(_loc(m.group(1), m.group(2), m.group(3)))
    m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", head[:1200])
    if m:
        _add(_loc(m.group(1), m.group(2), m.group(3)))
    # 仅信文首片段的无时刻 YYYY-MM-DD，降低正文历史数据误匹配
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", head[:520])
    if m:
        _add(_loc(m.group(1), m.group(2), m.group(3)))
    lead = (snip or "").strip()[:36]
    m = re.match(r"^(\d{1,2})-(\d{1,2})\s+\d{1,2}:\d{2}", lead)
    if m:
        mo, day = int(m.group(1)), int(m.group(2))
        now = datetime.now(tz)
        for y_cand in (now.year, now.year - 1):
            cand = _loc(str(y_cand), str(mo), str(day))
            if cand and cand.date() <= now.date() + timedelta(days=1):
                _add(cand)
                break
    if cands:
        # 仅对正文/URL 解析结果取最早；不把 Tavily 索引时间掺入 min，避免误判
        return min(cands)
    return tav_d


# 交易日盘后行业要闻：默认距今不超过 N 个自然日；主结果为空时自动放宽（见 recency_max_age_days）
INDUSTRY_NEWS_MAX_AGE_DAYS = 7
INDUSTRY_NEWS_RELAXED_MAX_AGE_DAYS = 14

# 权威来源（Tavily site:）；不含财富号/股吧；一财易混入星翼机编，默认不纳入站点白名单
_INDUSTRY_AUTHORITY_SITES = (
    "site:stcn.com OR site:cs.com.cn OR site:cls.cn OR site:finance.eastmoney.com"
)


def _industry_too_old_for_news(
    item: Dict[str, Any], *, max_age_days: int = INDUSTRY_NEWS_MAX_AGE_DAYS
) -> bool:
    """有确切发稿日时按自然日窗口过滤；无法断代时不剔除（已由 Tavily topic=news、days=7 约束召回）。"""
    pub = _industry_extract_pub_date(item)
    if pub is None:
        return False
    now = datetime.now(pytz.timezone("Asia/Shanghai"))
    if pub.date() > now.date():
        return False
    age_days = (now.date() - pub.date()).days
    return age_days > max_age_days


def _industry_source_score(item: Dict[str, Any]) -> int:
    """越高越优先：权威财经 / 东财正文频道。"""
    url = (item.get("url") or "").lower()
    s = 0
    if "stcn.com" in url or "cs.com.cn" in url:
        s += 4
    if "yicai.com" in url or "cls.cn" in url or "wallstreetcn.com" in url:
        s += 3
    if "finance.eastmoney.com/a/" in url or "stock.eastmoney.com/a/" in url:
        s += 2
    if "hexun.com" in url or "10jqka.com.cn" in url:
        s += 1
    if "caifuhao" in url or "guba." in url:
        s -= 6
    return s


def _industry_pick_items(
    raw_items: List[Dict[str, Any]],
    max_items: int,
    max_age_days: int,
) -> List[Dict[str, Any]]:
    scored: List[tuple] = []  # (score, item)
    for it in raw_items:
        if _industry_noise(it):
            continue
        if _industry_stale_or_clickbait_year(it):
            continue
        if _industry_too_old_for_news(it, max_age_days=max_age_days):
            continue
        if not _industry_relevant(it):
            continue
        scored.append((_industry_source_score(it), it))
    scored.sort(key=lambda x: -x[0])
    return [it for _, it in scored[:max_items]]


def tool_fetch_industry_news_brief(
    max_items: int = 5,
    use_cache: bool = True,
    disable_network: bool = False,
) -> Dict[str, Any]:
    """
    交易日盘后用的 A 股行业/板块线索（与政策要闻分工：景气、板块、调研为主）。

    仅使用 Tavily 检索 + **规则过滤**（硬/软规则、时效、来源白名单）；不在本函数内调用任何 LLM API。
    若需在成文阶段做语义筛选，由 OpenClaw Agent / 工作流在拿到本工具 JSON 后再处理。
    """
    cache_path = _cache_dir() / f"industry_news_{_today_str()}.json"
    if use_cache and cache_path.exists() and not disable_network:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("items"):
                return {"success": True, "message": "cache_hit", "data": cached}
        except Exception:
            pass

    if disable_network:
        return {
            "success": False,
            "message": "network_disabled",
            "data": {"items": [], "as_of": _today_str()},
        }

    _q_lang = " （检索回答请用中文概述近期行业与板块要点，不要用英文起句）"
    sites = _INDUSTRY_AUTHORITY_SITES
    # 两条议题互补：① 全市场行业/资金/轮动 ② 细分赛道 + 调研/景气（易出不同 URL）
    queries_primary = [
        f"A股 行业景气 板块轮动 资金配置 公募 外资 北向 {sites}{_q_lang}",
        f"半导体 新能源 医药 高端制造 新质生产力 券商调研 行业景气 {sites}{_q_lang}",
        f"A股 有色 煤炭 电力 光伏 锂电 产能 景气度 {sites}{_q_lang}",
        f"创新药 算力 电网设备 储能 产业链 行业分析 机构 {sites}{_q_lang}",
    ]
    merged_results: List[Dict[str, Any]] = []
    seen_rurl: set = set()
    answer = None
    any_tav_ok = False
    last_tav_err: Optional[str] = None
    per_n = max(18, max_items + 14)
    for q in queries_primary:
        tav = _tavily_search(
            q,
            n=per_n,
            topic="news",
            days=7,
            deep=False,
        )
        if not tav.get("success"):
            last_tav_err = tav.get("message") or last_tav_err
            continue
        any_tav_ok = True
        data = tav.get("data") or {}
        if answer is None and data.get("answer"):
            answer = data.get("answer")
        for r in data.get("results") or []:
            if not isinstance(r, dict):
                continue
            u = str(r.get("url") or "").strip()
            if not u or u in seen_rurl:
                continue
            seen_rurl.add(u)
            merged_results.append(r)
    if not any_tav_ok:
        return {
            "success": False,
            "message": last_tav_err or "tavily_failed",
            "data": {"items": [], "as_of": _today_str()},
        }
    # 合并结果常有数十条，勿按 max_items 截断过早，否则后面能通过时效/相关性的条被丢掉
    _cap = min(len(merged_results), 100)
    raw_items = _compact_results(merged_results, max(1, _cap), content_max=600)
    _industry_attach_tavily_published(raw_items, merged_results)
    age_limit = INDUSTRY_NEWS_MAX_AGE_DAYS
    items = _industry_pick_items(raw_items, max_items, age_limit)
    if not items:
        age_limit = INDUSTRY_NEWS_RELAXED_MAX_AGE_DAYS
        items = _industry_pick_items(raw_items, max_items, age_limit)
    # 双主题仍不足时：第三条检索（同权威站点 + 略宽关键词）
    if len(items) < max_items:
        q_fallback = (
            f"A股 行业景气 板块 公募 调研 外资 配置 有色 煤炭 电力 新质生产力 "
            f"新能源 医药 半导体 高端制造 {sites}{_q_lang}"
        )
        tav2 = _tavily_search(
            q_fallback,
            n=max(22, max_items + 16),
            topic="news",
            days=7,
            deep=False,
        )
        if tav2.get("success"):
            data2 = tav2.get("data") or {}
            more = _compact_results(
                data2.get("results") or [], 28, content_max=600
            )
            _industry_attach_tavily_published(more, data2.get("results") or [])
            seen = {x.get("url") for x in items}
            for it in more:
                if len(items) >= max_items:
                    break
                if (
                    _industry_noise(it)
                    or _industry_stale_or_clickbait_year(it)
                    or _industry_too_old_for_news(it, max_age_days=age_limit)
                    or not _industry_relevant(it)
                ):
                    continue
                u = it.get("url")
                if u in seen:
                    continue
                items.append(it)
                seen.add(u)
    if not items:
        items = [
            it
            for it in raw_items
            if not _industry_noise(it)
            and not _industry_stale_or_clickbait_year(it)
            and not _industry_too_old_for_news(it, max_age_days=age_limit)
            and _industry_relevant(it)
        ][:max_items]
    items = items[:max_items]
    for it in items:
        it.pop("published_date", None)
        it["category"] = "industry"

    brief = str(answer).strip()[:500] if answer else None
    if brief:
        low = brief[:120].lower()
        if low.startswith("based on") or low.startswith("according to"):
            if items:
                t0 = (items[0].get("title") or "")[:100]
                brief = (
                    f"行业与板块检索要点：可关注「{t0}」等；详情见下方链接（请以原文为准）。"
                )
            else:
                brief = "行业检索摘要：见下方链接（请以原文为准）。"
    payload = {
        "as_of": datetime.now(pytz.timezone("Asia/Shanghai")).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "brief_answer": brief,
        "items": items,
        "numeric_unverified": True,
        "source_type": "search",
        "recency_max_age_days": age_limit,
    }
    try:
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass

    return {"success": True, "message": "ok", "data": payload}
