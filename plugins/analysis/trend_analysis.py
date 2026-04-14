"""趋势分析插件：封装原系统 trend_analyzer；叙事由 OpenClaw + ota_openclaw_tool_narration（不再进程内 llm_enhancer）。"""

import sys
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

# 导入交易日判断工具
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
utils_path = os.path.join(parent_dir, 'utils')
if utils_path not in sys.path:
    sys.path.insert(0, utils_path)

try:
    from plugins.utils.trading_day import check_trading_day_before_operation
    TRADING_DAY_CHECK_AVAILABLE = True
except ImportError:
    TRADING_DAY_CHECK_AVAILABLE = False
    def check_trading_day_before_operation(*args, **kwargs):
        return None

# 尝试将当前环境中的本地 src 根目录加入 Python 路径
selected_root: Optional[Path] = None
for parent in Path(__file__).resolve().parents:
    if (parent / "src").exists():
        selected_root = parent
        break
if selected_root is not None and str(selected_root) not in sys.path:
    sys.path.insert(0, str(selected_root))

logger = logging.getLogger(__name__)

try:
    # 导入原系统的分析模块
    from src.trend_analyzer import (
        analyze_daily_market_after_close,
        analyze_market_before_open,
        analyze_opening_market
    )
    # 这些模块可能不存在，使用可选导入
    try:
        from src.config_loader import load_system_config
    except ImportError:
        load_system_config = None

    try:
        from src.data_collection.index import fetch_index_opening_data
    except ImportError:
        fetch_index_opening_data = None

    ORIGINAL_SYSTEM_AVAILABLE = True
except ImportError as e:
    ORIGINAL_SYSTEM_AVAILABLE = False
    IMPORT_ERROR = str(e)


_DEFAULT_GLOBAL_INDEX_CODES = (
    "^N225,^HSI,^KS11,^GDAXI,^STOXX50E,^FTSE,^GSPC,^IXIC,^DJI"
)

def _known_index_facts_for_tavily_prose(base_rows: List[Dict[str, Any]], codes_order: List[str]) -> str:
    """主行情接口已确认的涨跌幅，供 LLM 强制对齐，避免与恒生等已知数矛盾。"""
    from plugins.data_collection.index.fetch_global import SYMBOL_NAME_MAP

    lines: List[str] = []
    for code in codes_order:
        row = next(
            (
                r
                for r in base_rows
                if isinstance(r, dict) and str(r.get("code") or "").strip() == code
            ),
            None,
        )
        if not row or row.get("change_pct") is None:
            continue
        nm = SYMBOL_NAME_MAP.get(code, str(row.get("name") or code))
        try:
            cp = float(row["change_pct"])
        except (TypeError, ValueError):
            continue
        lines.append(f"- {nm}（{code}）：**{cp:+.4g}%**（主数据源已确认）")
    if not lines:
        return ""
    return "【接口已确认（综述中凡提及下列指数时，涨跌幅必须与之一致；不得改写符号或数值）】\n" + "\n".join(lines)


def _gather_dual_tavily_global_material(ov: Dict[str, Any]) -> tuple[str, str]:
    """
    外盘专用：双路 Tavily（美股指 + 亚欧股指）。通用检索 API 见 plugins.utils.tavily_client。
    """
    from plugins.utils.tavily_client import (
        DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS,
        parse_include_domains,
        tavily_gather_batch_searches,
    )

    domains = parse_include_domains(
        ov.get("tavily_global_include_domains"),
        default=DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS,
    )
    deep = bool(ov.get("tavily_global_deep", True))
    days = int(ov.get("tavily_global_days", 2) or 2)
    mx = max(3, min(int(ov.get("tavily_global_max_results", 6) or 6), 12))

    q_us = str(ov.get("tavily_global_query_us") or "").strip() or (
        "Dow Jones Industrial Average S&P 500 Nasdaq Composite stock index "
        "percentage change prior regular session close"
    )
    q_row = str(ov.get("tavily_global_query_row") or "").strip() or (
        "Hang Seng Index Nikkei 225 KOSPI KRX South Korea composite stock index "
        "DAX EURO STOXX 50 FTSE 100 percentage change market close"
    )

    batches: List[Dict[str, str]] = [
        {"header": "检索批次：美洲主要股指", "query": q_us},
        {"header": "检索批次：亚欧主要股指", "query": q_row},
    ]
    return tavily_gather_batch_searches(
        batches,
        include_domains=domains,
        max_results=mx,
        days=days,
        deep=deep,
        topic="news",
    )


def _merge_trend_plugin_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """合并 config['trend_analysis_plugin'] 与默认值（与 config_loader 默认语义一致）。"""
    defaults: Dict[str, Any] = {
        "enabled": True,
        "opening_dir": None,
        "overlay": {
            "northbound_enabled": True,
            "northbound_lookback_days": 5,
            "global_index_enabled": True,
            "global_index_codes": _DEFAULT_GLOBAL_INDEX_CODES,
            "key_levels_enabled": True,
            "key_levels_index": "000300",
            "sector_heat_enabled": True,
            "adx_enabled": False,
            "adx_index": "000300",
            "adx_lookback_days": 60,
        },
        "fallback": {
            "use_simple_opening": True,
            "simple_opening_include_volume_weighted": True,
        },
    }
    if not config:
        return defaults
    user = config.get("trend_analysis_plugin")
    if not isinstance(user, dict):
        return defaults
    out = {**defaults, **{k: v for k, v in user.items() if k not in ("overlay", "fallback")}}
    if isinstance(user.get("overlay"), dict):
        out["overlay"] = {**defaults["overlay"], **user["overlay"]}
    if isinstance(user.get("fallback"), dict):
        out["fallback"] = {**defaults["fallback"], **user["fallback"]}
    return out


def _sector_heat_summary_line(sh: Dict[str, Any]) -> str:
    sectors = sh.get("sectors") or []
    if not sectors:
        return ""
    parts: List[str] = []
    for s in sectors[:3]:
        name = (s.get("name") or "").strip()
        score = s.get("score")
        if name and score is not None:
            parts.append(f"{name}({score})")
    if not parts:
        return ""
    return "、".join(parts) + " 热度领先"


def _trend_text_to_sentiment_score(t: str) -> float:
    m = {
        "强势": 0.75,
        "偏强": 0.4,
        "震荡": 0.0,
        "谨慎": 0.0,
        "中性": 0.0,
        "偏弱": -0.4,
        "弱势": -0.75,
    }
    return m.get(str(t).strip(), 0.0)


def _derive_market_sentiment_score(analysis_type: str, ar: Dict[str, Any]) -> float:
    if analysis_type == "after_close":
        rr = ar.get("rising_ratio")
        if isinstance(rr, (int, float)):
            return max(-1.0, min(1.0, (float(rr) - 0.5) * 2.0))
        return _trend_text_to_sentiment_score(str(ar.get("overall_trend", "")))
    if analysis_type == "before_open":
        return _trend_text_to_sentiment_score(str(ar.get("final_trend", "")))
    if analysis_type == "opening_market":
        summ = ar.get("summary")
        if isinstance(summ, dict):
            strong = int(summ.get("strong_count") or 0)
            weak = int(summ.get("weak_count") or 0)
            total_edge = strong + weak
            if total_edge > 0:
                return max(-1.0, min(1.0, (strong - weak) / total_edge))
        inner = ar.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("summary"), dict):
            ss = inner["summary"].get("sentiment_score")
            if isinstance(ss, (int, float)):
                return max(-1.0, min(1.0, float(ss)))
    return 0.0


def _derive_trend_strength_label(analysis_type: str, ar: Dict[str, Any]) -> str:
    o = ar.get("daily_report_overlay") or {}
    ts = o.get("trend_strength")
    if isinstance(ts, dict):
        sig = str(ts.get("signal") or "")
        if "较强" in sig:
            return "strong"
        if "较弱" in sig:
            return "weak"
        return "neutral"
    if analysis_type == "after_close":
        ot = str(ar.get("overall_trend", ""))
        if ot == "强势":
            return "strong"
        if ot == "弱势":
            return "weak"
    if analysis_type == "before_open":
        ft = str(ar.get("final_trend", ""))
        if ft == "强势":
            return "strong"
        if ft == "弱势":
            return "weak"
    return "neutral"


def _build_key_metrics(analysis_type: str, ar: Dict[str, Any]) -> Dict[str, Any]:
    if analysis_type == "after_close":
        return {
            "date": ar.get("date"),
            "overall_trend": ar.get("overall_trend"),
            "trend_strength": ar.get("trend_strength"),
            "rising_ratio": ar.get("rising_ratio"),
        }
    if analysis_type == "before_open":
        return {
            "date": ar.get("date"),
            "after_close_basis": ar.get("after_close_basis"),
            "final_trend": ar.get("final_trend"),
            "final_strength": ar.get("final_strength"),
            "effective_overnight_change": ar.get("effective_overnight_change"),
        }
    summ = ar.get("summary") if isinstance(ar.get("summary"), dict) else {}
    inner = ar.get("data") if isinstance(ar.get("data"), dict) else {}
    inner_sum = inner.get("summary") if isinstance(inner.get("summary"), dict) else {}
    return {
        "summary": summ or inner_sum or {},
    }


def _attach_report_meta(
    analysis_type: str,
    analysis_result: Dict[str, Any],
) -> None:
    """统一解析友好字段；不修改或删除原有键。"""
    overlay = analysis_result.get("daily_report_overlay")
    if not isinstance(overlay, dict):
        overlay = {}
    meta: Dict[str, Any] = {
        "analysis_type": analysis_type,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "market_sentiment_score": round(_derive_market_sentiment_score(analysis_type, analysis_result), 4),
        "trend_strength_label": _derive_trend_strength_label(analysis_type, analysis_result),
        "key_metrics": _build_key_metrics(analysis_type, analysis_result),
        "overlay": dict(overlay) if overlay else {},
    }
    # 非交易日：防止 cron Agent 误判「无法分析」而只发钉钉短讯（绕过 tool_send_daily_report）
    if analysis_type == "after_close":
        try:
            import pytz
            from plugins.utils.trading_day import is_trading_day

            tz = pytz.timezone("Asia/Shanghai")
            now = datetime.now(tz)
            meta["calendar_date_yyyymmdd"] = now.strftime("%Y%m%d")
            if not is_trading_day(now, None):
                meta["non_trading_calendar_day"] = True
                meta["daily_report_cron_contract"] = (
                    "日历日为非 A 股交易日：本工具已返回 **success** 的盘后复盘，"
                    "结论基于指数日线**最近可用交易日**收市数据（见 data_stale_warning / 各指数日期字段），属正常口径。"
                    "下一步**必须**调用 `tool_analyze_after_close_and_send_daily_report(mode=prod)` "
                    "（推荐）或 `tool_send_daily_report` 发出**标准收评式 Markdown 日报**（含章节与 DAILY_REPORT_STATUS 审计行）。"
                    "**禁止**用 `tool_send_dingtalk_message` 发送「无法获取当日数据」「非交易日降级版」等短讯替代正式日报；"
                    "**禁止**虚构 `MISSING_FIELDS=NON_TRADING_DAY` 或谎称 `CORE_ANALYSIS` 缺失。"
                )
        except Exception:
            pass
    analysis_result["report_meta"] = meta


def _tavily_fallback_northbound(ov: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """接口失败时用 Tavily 检索北向等定性摘要（非交易所原始数值）。"""
    if not ov.get("tavily_fallback_enabled", True):
        return None
    try:
        from datetime import datetime

        from plugins.utils.tavily_client import tavily_effective_answer_text, tavily_search

        q = str(ov.get("tavily_northbound_query") or "沪深港通 北向资金 净流入 最新").strip()
        t = tavily_search(q, max_results=4, days=2)
        if not t.get("success"):
            return None
        text = tavily_effective_answer_text(t)
        if not text.strip():
            return None
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "status": "success",
            "date": today,
            "data": {"total_net": None, "sh_net": None, "sz_net": None},
            "statistics": {"trend": "网络检索摘要"},
            "signal": {
                "description": f"（Tavily 摘要，非交易所接口原始值）{text[:650]}",
            },
            "source": "tavily_fallback",
        }
    except Exception as e:
        logger.warning("tavily northbound fallback: %s", e)
        return None


def _tavily_fallback_global_digest(ov: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """外盘/yfinance 失败时用 Tavily（权威域名优先 + 双路检索）拼全球股指摘要。"""
    if not ov.get("tavily_fallback_enabled", True):
        return None
    try:
        from plugins.utils.tavily_client import (
            DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS,
            parse_include_domains,
            tavily_effective_answer_text,
            tavily_search_with_include_domain_fallback,
        )

        material, digest_short = _gather_dual_tavily_global_material(ov)
        text = (digest_short or material or "").strip()
        if not text:
            domains = parse_include_domains(
                ov.get("tavily_global_include_domains"),
                default=DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS,
            )
            deep = bool(ov.get("tavily_global_deep", True))
            days = int(ov.get("tavily_global_days", 2) or 2)
            mx = max(3, min(int(ov.get("tavily_global_max_results", 6) or 6), 12))
            q = str(
                ov.get("tavily_global_query") or "全球股市 道琼斯 纳斯达克 标普 恒生 最新 涨跌"
            ).strip()
            t = tavily_search_with_include_domain_fallback(
                q, max_results=mx, days=days, deep=deep, include_domains=domains
            )
            if not t.get("success"):
                return None
            text = tavily_effective_answer_text(t).strip()
            if not text:
                return None
        return {
            "summary": text[:1500],
            "source": "tavily_fallback",
            "replaces_index_overview": True,
        }
    except Exception as e:
        logger.warning("tavily global digest fallback: %s", e)
        return None


def _outer_market_tavily_prose_instructions(codes_list: List[str]) -> str:
    """Tavily 兜底：LLM 只写股指综述；严控数字幻觉与大宗商品串台。"""
    from plugins.data_collection.index.fetch_global import SYMBOL_NAME_MAP

    names = [SYMBOL_NAME_MAP.get(c, c) for c in codes_list]
    markets = "、".join(names)
    return f"""请仅根据下方「检索批次」中的英文/中文财经报道摘要，用中文写一段「全球主要股指」综述（约 4～8 句，单段连续正文）。

应覆盖或自然点到这些指数/市场：{markets}。若检索对某一市场几乎无着墨，用一句自然财经中文带过即可（**禁止**出现「素材未涉及」「检索未涉及」等面向系统的元话语）。

硬性规则（违反任一条即视为不合格稿，须自我修正后再输出）：
1) **股票指数专述**：只写股票指数（股指、大盘、道指/纳指/标普、恒指、日经、KOSPI、DAX、斯托克、富时等）。**不得**写原油、黄金、铜、农产品、加密货币、美元指数等大宗商品或另类资产，除非检索原文**同一句**内明确把油价等与股指走势绑在一起分析（此类情况至多一句带过）。
2) **数字纪律**：凡素材中**未同时出现**「具体指数或市场名称」与「阿拉伯数字涨跌幅（含 % 或 点）」的，**禁止**为该市场写出形如「上涨 0.5%」「收跌 0.3%」等任何带 % 的数字。**禁止**用常识或历史行情猜测数字。
3) **与上文「接口已确认」块一致**：若上文列出某指数已确认涨跌幅，你在综述中写到该指数时，**数值与正负号必须与上文完全一致**；已确认的指数**不得**再写「未披露」「未报道」等与上文矛盾的话。
4) 文风：不要 JSON、不要 markdown 围栏、不要「一、二、」编号；不要自称模型；不要复述本说明文字。"""


def _global_index_missing_pct(gspot: Any, codes_csv: str) -> bool:
    """配置的代码列表中是否仍有指数缺 change_pct（需 Tavily 摘要时返回 True）。"""
    codes_list = [c.strip() for c in (codes_csv or "").split(",") if c.strip()]
    want = len(codes_list)
    if want <= 0:
        return False
    rows: List[Dict[str, Any]] = []
    if isinstance(gspot, dict):
        raw = gspot.get("data")
        if isinstance(raw, list):
            rows = [x for x in raw if isinstance(x, dict)]
    quoted = sum(1 for r in rows if r.get("change_pct") is not None)
    return quoted < want


def _supplement_global_index_tavily_llm(
    ov: Dict[str, Any],
    codes: str,
    base: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    当仍有指数缺 change_pct：Tavily 检索 → LLM 写**外盘综述段落**（摘要-only），
    不再抽取逐指数 JSON。报告「外盘/指数概览」行由综述覆盖，避免整行 N/A。
    """
    if not ov.get("global_index_tavily_llm_enabled", True):
        return None
    try:
        from src.config_loader import load_system_config as _lsc

        cfg = _lsc(use_cache=True)
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    ext = cfg.get("llm_structured_extract") or {}
    if not isinstance(ext, dict):
        ext = {}

    codes_list = [c.strip() for c in (codes or "").split(",") if c.strip()]
    if not codes_list:
        return None

    base_rows = list((base or {}).get("data") or []) if isinstance(base, dict) else []
    want = len(codes_list)

    def _rows_with_numeric_change_pct(rows: List[Dict[str, Any]]) -> int:
        n = 0
        for r in rows:
            if not isinstance(r, dict):
                continue
            if r.get("change_pct") is not None:
                n += 1
        return n

    quoted = _rows_with_numeric_change_pct(base_rows)
    if quoted >= want:
        return None

    try:
        from plugins.utils.llm_structured_extract import llm_prose_from_unstructured
    except ImportError as e:
        logger.warning("daily_report_overlay: tavily+llm 依赖缺失: %s", e)
        return None

    material, digest_short = _gather_dual_tavily_global_material(ov)
    if not material.strip():
        logger.warning("daily_report_overlay: Tavily 双路检索均无可用文本")
        return None

    max_raw = int((ext or {}).get("max_raw_text_chars", 12000))
    raw_text = material[:max_raw]
    digest = (digest_short or raw_text).strip()[:1200]

    facts = _known_index_facts_for_tavily_prose(base_rows, codes_list)
    ins = _outer_market_tavily_prose_instructions(codes_list)
    user_instructions = (facts + "\n\n---\n\n" + ins) if facts.strip() else ins

    prose: Optional[str] = None
    llm_meta: Any = None
    if ext.get("enabled"):
        profile = str(ov.get("llm_structured_extract_profile") or "default").strip() or "default"
        r = llm_prose_from_unstructured(raw_text, user_instructions, profile=profile, config=cfg)
        if r.get("success") and isinstance(r.get("text"), str) and r["text"].strip():
            prose = r["text"].strip()
            llm_meta = r.get("meta")
        else:
            logger.info(
                "daily_report_overlay: Tavily 外盘综述 LLM 未成功，使用检索原文摘要: %s",
                (r or {}).get("message"),
            )

    if not prose:
        prose = digest

    out: Dict[str, Any] = dict(base) if isinstance(base, dict) else {"success": True, "data": []}
    out["success"] = True
    out["data"] = base_rows
    out["count"] = len(base_rows)
    out["tavily_answer_digest"] = digest
    out["outer_market_tavily_summary"] = prose[:2000]
    out["outer_market_summary_replaces_overview"] = True
    prev = str(out.get("source") or "").strip()
    out["source"] = f"{prev}+tavily_llm_prose" if prev else "tavily_llm_prose"
    if llm_meta is not None:
        out["tavily_llm_prose_meta"] = llm_meta

    if isinstance(base, dict) and base.get("fetch_failures") is not None:
        out["fetch_failures"] = base.get("fetch_failures")

    return out


def _attach_daily_report_overlay(
    analysis_result: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """
    为每日市场报告附加结构化字段（北向、全球指数现货、关键位、板块热度、可选 ADX）。
    任一步失败则跳过，不抛异常。
    """
    plugin = _merge_trend_plugin_config(config)
    if not plugin.get("enabled", True):
        return

    ov = plugin.get("overlay") or {}
    overlay: Dict[str, Any] = {}

    nb_ok = False
    if ov.get("northbound_enabled", True):
        try:
            from plugins.data_collection.northbound import tool_fetch_northbound_flow

            days = int(ov.get("northbound_lookback_days", 5))
            nb = tool_fetch_northbound_flow(lookback_days=days)
            if isinstance(nb, dict) and nb.get("status") == "success":
                overlay["northbound"] = nb
                nb_ok = True
        except Exception as e:
            logger.warning("daily_report_overlay: northbound 接口异常: %s", e)
        if not nb_ok:
            fb_nb = _tavily_fallback_northbound(ov)
            if fb_nb:
                overlay["northbound"] = fb_nb
                logger.info("daily_report_overlay: northbound 已使用 Tavily 兜底")

    g_ok = False
    if ov.get("global_index_enabled", True):
        try:
            from plugins.data_collection.index.fetch_global import tool_fetch_global_index_spot

            codes = str(ov.get("global_index_codes") or _DEFAULT_GLOBAL_INDEX_CODES)
            g = tool_fetch_global_index_spot(index_codes=codes)
            merged: Optional[Dict[str, Any]] = None
            if isinstance(g, dict):
                merged = _supplement_global_index_tavily_llm(ov, codes, g)
            if merged is not None:
                overlay["global_index_spot"] = merged
                g_ok = True
                if merged.get("outer_market_tavily_summary"):
                    overlay["global_market_digest"] = {
                        "summary": merged["outer_market_tavily_summary"],
                        "source": "tavily_llm_prose",
                        "replaces_index_overview": True,
                    }
                logger.info("daily_report_overlay: global_index_spot 已合并 Tavily 外盘综述（摘要-only）")
            elif isinstance(g, dict) and g.get("success") and isinstance(g.get("data"), list) and len(g["data"]) > 0:
                overlay["global_index_spot"] = g
                g_ok = True
        except Exception as e:
            logger.warning("daily_report_overlay: global_index_spot 接口异常: %s", e)
        if not g_ok:
            fb_g = _tavily_fallback_global_digest(ov)
            if fb_g:
                overlay["global_market_digest"] = fb_g
                logger.info("daily_report_overlay: 外盘概览已使用 Tavily 摘要兜底")
        elif g_ok and ov.get("tavily_fallback_enabled", True):
            gspot = overlay.get("global_index_spot")
            codes_chk = str(ov.get("global_index_codes") or _DEFAULT_GLOBAL_INDEX_CODES)
            if _global_index_missing_pct(gspot, codes_chk) and overlay.get("global_market_digest") is None:
                fb_g2 = _tavily_fallback_global_digest(ov)
                if fb_g2:
                    overlay["global_market_digest"] = fb_g2
                    logger.info("daily_report_overlay: 指数仍缺涨跌幅项，已补 Tavily 外盘摘要")

    if ov.get("key_levels_enabled", True):
        try:
            from plugins.analysis.key_levels import tool_compute_index_key_levels

            idx = str(ov.get("key_levels_index") or "000300")
            kl = tool_compute_index_key_levels(index_code=idx)
            if isinstance(kl, dict) and kl.get("success"):
                overlay[f"key_levels_{idx}"] = kl
                # 与 send_daily_report 归一化字段对齐，避免仅依赖 key_levels_* 形态
                overlay["key_levels"] = kl
        except Exception:
            pass

    # 日频全日波动区间：日报完整性判定依赖；须在盘后分析内产出，勿依赖 send 层拉取
    if ov.get("daily_volatility_range_enabled", True):
        try:
            from plugins.analysis.daily_volatility_range import tool_predict_daily_volatility_range

            und = str(ov.get("volatility_underlying") or "510300").strip()
            dv = tool_predict_daily_volatility_range(underlying=und)
            if isinstance(dv, dict) and dv.get("success"):
                overlay["daily_volatility_range"] = dv
            elif isinstance(dv, dict):
                overlay["daily_volatility_range_error"] = dv.get("message") or "daily_volatility_range_failed"
                logger.warning(
                    "daily_report_overlay: daily_volatility_range 未成功: %s",
                    overlay.get("daily_volatility_range_error"),
                )
        except Exception as e:
            logger.warning("daily_report_overlay: daily_volatility_range 异常: %s", e)

    # 期权/ETF 交易信号：与日报「信号」章节对齐（上游一次性合并）
    if ov.get("option_signals_enabled", True):
        try:
            from plugins.analysis.signal_generation import tool_generate_option_trading_signals

            und = str(ov.get("signals_underlying") or ov.get("volatility_underlying") or "510300").strip()
            sg = tool_generate_option_trading_signals(underlying=und, mode="production")
            if isinstance(sg, dict) and sg.get("success") and isinstance(sg.get("data"), dict):
                d0 = sg["data"]
                sigs = d0.get("signals")
                if isinstance(sigs, list):
                    overlay["signals"] = sigs
                else:
                    overlay["signals"] = d0
            elif isinstance(sg, dict):
                overlay["signals_error"] = sg.get("message") or "signals_failed"
                logger.warning("daily_report_overlay: option signals 未成功: %s", overlay.get("signals_error"))
        except Exception as e:
            logger.warning("daily_report_overlay: option signals 异常: %s", e)

    if ov.get("sector_heat_enabled", True):
        try:
            from plugins.data_collection.limit_up.sector_heat import tool_sector_heat_score

            sh = tool_sector_heat_score()
            if isinstance(sh, dict) and sh.get("success", True) and not sh.get("error"):
                overlay["sector_heat"] = sh
        except Exception:
            pass

    # 两市量能摘要：上证日线最近两日成交额环比（依赖本地 index_daily 缓存）
    if ov.get("market_volume_digest_enabled", True):
        try:
            from datetime import datetime, timedelta

            from plugins.merged.read_market_data import tool_read_market_data

            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=45)
            r = tool_read_market_data(
                data_type="index_daily",
                symbol="000001",
                start_date=start_dt.strftime("%Y%m%d"),
                end_date=end_dt.strftime("%Y%m%d"),
            )
            if isinstance(r, dict) and r.get("success"):
                payload = r.get("data")
                recs = payload.get("records") if isinstance(payload, dict) else None
                if isinstance(recs, list) and len(recs) >= 2:
                    last, prev = recs[-1], recs[-2]
                    amt_k = None
                    for k in ("amount", "成交额", "turnover", "total_turnover"):
                        if k in last and k in prev:
                            amt_k = k
                            break
                    if amt_k:
                        try:
                            a0 = float(last.get(amt_k) or 0)
                            a1 = float(prev.get(amt_k) or 0)
                            dod = ((a0 - a1) / a1 * 100.0) if a1 > 0 else None
                            overlay["market_volume_digest"] = {
                                "benchmark": "上证指数",
                                "metric": "成交额",
                                "latest": a0,
                                "previous": a1,
                                "dod_pct": dod,
                                "source": "index_daily_cache",
                            }
                        except (TypeError, ValueError):
                            pass
        except Exception as e:
            logger.warning("daily_report_overlay: market_volume_digest: %s", e)

    # 第二宽基（中证500 ETF）当日涨跌摘要
    sec_etf = str(ov.get("secondary_benchmark_etf") or "510500").strip()
    if sec_etf:
        try:
            from plugins.data_collection.etf.fetch_realtime import tool_fetch_etf_realtime

            er = tool_fetch_etf_realtime(etf_code=sec_etf, mode="production")
            if isinstance(er, dict) and er.get("success") and isinstance(er.get("data"), dict):
                d0 = er["data"]
                overlay["secondary_benchmark_etf"] = {
                    "code": sec_etf,
                    "name": d0.get("name") or d0.get("etf_name") or sec_etf,
                    "change_pct": d0.get("change_pct") or d0.get("change_percent"),
                    "current_price": d0.get("current_price") or d0.get("price"),
                }
        except Exception as e:
            logger.warning("daily_report_overlay: secondary_benchmark_etf: %s", e)

    if ov.get("adx_enabled", False):
        try:
            from plugins.analysis.technical_indicators import calculate_technical_indicators

            idx = str(ov.get("adx_index") or ov.get("key_levels_index") or "000300")
            lb = int(ov.get("adx_lookback_days", 60))
            adx_r = calculate_technical_indicators(
                symbol=idx,
                data_type="index_daily",
                indicators=["adx"],
                lookback_days=lb,
            )
            if adx_r.get("success") and isinstance(adx_r.get("data"), dict):
                ind = adx_r["data"].get("indicators", {}).get("adx")
                if isinstance(ind, dict) and "error" not in ind:
                    overlay["trend_strength"] = {
                        "symbol": idx,
                        "adx": ind.get("adx"),
                        "signal": ind.get("signal"),
                        "length": ind.get("length"),
                    }
        except Exception:
            pass

    if overlay:
        analysis_result["daily_report_overlay"] = overlay


def _attach_overnight_overlay_opening(analysis_result: Dict[str, Any]) -> None:
    """
    开盘晨报正文依赖 analysis.a50_change / hxc_change；原 analyze_opening_market 不含隔夜字段，
    导致报告中 A50/金龙恒为「获取失败」。与盘前同源补拉 A50 + 金龙（失败则保留 degraded 标记）。
    """
    if analysis_result.get("a50_change") is not None or analysis_result.get("hxc_change") is not None:
        return
    if not ORIGINAL_SYSTEM_AVAILABLE:
        return
    try:
        from src.trend_analyzer import fetch_a50_futures_data, fetch_nasdaq_golden_dragon

        a50_data = fetch_a50_futures_data()
        hxc_data = fetch_nasdaq_golden_dragon()
        analysis_result["a50_change"] = a50_data.get("change_pct")
        analysis_result["hxc_change"] = hxc_data.get("change_pct")
        analysis_result["a50_status"] = a50_data.get("status")
        analysis_result["hxc_status"] = hxc_data.get("status")
        analysis_result["a50_reason"] = a50_data.get("reason")
        analysis_result["hxc_reason"] = hxc_data.get("reason")
        eff = analysis_result.get("a50_change")
        if eff is None:
            eff = analysis_result.get("hxc_change")
        analysis_result["overnight_overlay_degraded"] = eff is None
    except Exception:
        pass


def trend_analysis(
    analysis_type: str = "after_close",  # "after_close", "before_open", "opening_market"
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    执行趋势分析（融合原系统逻辑和 LLM 增强）

    Args:
        analysis_type: 分析类型（"after_close", "before_open", "opening_market"）
        api_base_url: 原系统 API 基础地址（保留用于未来扩展）
        api_key: API Key（保留用于未来扩展）

    隔夜 A50 / 纳斯达克中国金龙（HXC）由 ``before_open`` 在 ``analyze_market_before_open`` 内拉取；
    ``opening_market`` 在趋势分析完成后会补拉同源 A50/HXC（见 ``_attach_overnight_overlay_opening``），
    以便晨报正文的 A50/金龙行不再恒为「获取失败」。``after_close`` 的 overlay 仍独立于此。

    Returns:
        Dict: 包含分析结果和 LLM 增强的字典
    """
    try:
        # ========== 交易日判断（仅用于提示，不阻止执行） ==========
        if TRADING_DAY_CHECK_AVAILABLE:
            operation_name_map = {
                "after_close": "盘后分析",
                "before_open": "盘前分析",
                "opening_market": "开盘分析"
            }
            operation_name = operation_name_map.get(analysis_type, "趋势分析")
            trading_day_check = check_trading_day_before_operation(operation_name)
            if trading_day_check:
                pass
        # ========== 交易日判断结束 ==========

        config: Optional[Dict[str, Any]] = None
        if ORIGINAL_SYSTEM_AVAILABLE:
            try:
                config = load_system_config(use_cache=True)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"配置加载失败，忽略: {e}", exc_info=True)

        plugin = _merge_trend_plugin_config(config)

        analysis_result = None
        if analysis_type == "after_close":
            if ORIGINAL_SYSTEM_AVAILABLE:
                analysis_result = analyze_daily_market_after_close(config=config)
            else:
                return {
                    'success': False,
                    'message': '盘后分析需要原系统模块，当前不可用',
                    'data': None
                }
        elif analysis_type == "before_open":
            if ORIGINAL_SYSTEM_AVAILABLE:
                analysis_result = analyze_market_before_open(config=config)
            else:
                return {
                    'success': False,
                    'message': '盘前分析需要原系统模块，当前不可用',
                    'data': None
                }
        elif analysis_type == "opening_market":
            # ---------- 开盘数据链优先级（同级只走一条成功路径）----------
            # 1) 原系统 fetch_index_opening_data
            # 2) OpenClaw plugins...fetch_index_opening（仅当 1 失败）
            # 分析优先级：analyze_opening_market → 异常时若 fallback.use_simple_opening 则 _simple_opening_analysis
            try:
                opening_data_result = None
                if ORIGINAL_SYSTEM_AVAILABLE and fetch_index_opening_data is not None:
                    try:
                        opening_data_result = fetch_index_opening_data()
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"原系统 fetch_index_opening_data 调用失败: {e}")
                        opening_data_result = None

                if not opening_data_result or not opening_data_result.get('success'):
                    try:
                        from plugins.data_collection.index.fetch_opening import fetch_index_opening

                        opening_data_result = fetch_index_opening(mode="test")
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"OpenClaw fetch_index_opening 调用失败: {e}")

                if opening_data_result and opening_data_result.get('success'):
                    opening_data = opening_data_result.get('data', [])
                    fb = plugin.get("fallback") or {}
                    use_simple = fb.get("use_simple_opening", True)

                    if ORIGINAL_SYSTEM_AVAILABLE and analyze_opening_market is not None:
                        try:
                            analysis_result = analyze_opening_market(
                                opening_data={item['code']: item for item in opening_data},
                                config=config
                            )
                        except Exception as e:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.warning(
                                f"原系统 analyze_opening_market 调用失败: {e}"
                            )
                            if not use_simple:
                                return {
                                    'success': False,
                                    'message': f'开盘分析失败且已禁用简化版: {e}',
                                    'data': None
                                }
                            analysis_result = _simple_opening_analysis(opening_data, config)
                    else:
                        analysis_result = _simple_opening_analysis(opening_data, config)
                else:
                    return {
                        'success': False,
                        'message': f'获取开盘数据失败：{opening_data_result.get("message", "Unknown error") if opening_data_result else "No data"}',
                        'data': None
                    }
            except Exception as e:
                import traceback
                return {
                    'success': False,
                    'message': f'开盘分析执行失败：{str(e)}',
                    'data': None,
                    'traceback': traceback.format_exc()
                }
        else:
            return {
                'success': False,
                'message': f'不支持的分析类型：{analysis_type}',
                'data': None
            }

        if analysis_result is None:
            return {
                'success': False,
                'message': '分析函数返回 None',
                'data': None
            }

        if (
            analysis_type == "after_close"
            and isinstance(analysis_result, dict)
            and plugin.get("enabled", True)
        ):
            _attach_daily_report_overlay(analysis_result, config)

        if analysis_type == "opening_market" and isinstance(analysis_result, dict):
            _attach_overnight_overlay_opening(analysis_result)

        if isinstance(analysis_result, dict):
            _attach_report_meta(analysis_type, analysis_result)

        has_llm_enhancement = 'llm_summary' in analysis_result and analysis_result.get('llm_summary')

        try:
            from src.data_storage import save_trend_analysis

            if save_trend_analysis(analysis_result, analysis_type=analysis_type, config=config):
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"趋势分析数据已保存到文件（供仪表盘读取）: {analysis_type}")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"保存趋势分析数据到文件失败（不影响分析功能）: {str(e)}")

        return {
            'success': True,
            'message': f'{analysis_type} analysis completed',
            'data': analysis_result,
            'llm_enhanced': has_llm_enhancement
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


def tool_analyze_after_close(**kwargs: Any) -> Dict[str, Any]:
    """OpenClaw 工具：盘后分析。合并路由会把 Agent 多传的键（如 report_date）经 **kwargs 传入，须吸收以免 TypeError。"""
    if kwargs:
        logger.debug("tool_analyze_after_close: ignoring kwargs %s", sorted(kwargs.keys()))
    return trend_analysis(analysis_type="after_close")


def tool_analyze_before_open(**kwargs: Any) -> Dict[str, Any]:
    """OpenClaw 工具：盘前分析（隔夜 A50/HXC 仅本入口使用，失败时见 overnight_overlay_degraded）。"""
    if kwargs:
        logger.debug("tool_analyze_before_open: ignoring kwargs %s", sorted(kwargs.keys()))
    return trend_analysis(analysis_type="before_open")


def _simple_opening_analysis(
    opening_data: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    简化版开盘分析（不依赖原系统 analyze_opening_market）。

    opening_data 项兼容 fetch_index_opening：opening_price / pre_close / change_pct / volume 等。
    """
    if not opening_data:
        return {
            'success': False,
            'message': '无开盘数据',
            'data': None
        }

    plugin = _merge_trend_plugin_config(config)
    fb = plugin.get("fallback") or {}
    include_vol_weighted = fb.get("simple_opening_include_volume_weighted", True)
    lookback = 5
    if isinstance(config, dict):
        lookback = int(config.get("opening_analysis", {}).get("lookback_days", 5))

    index_analysis: Dict[str, Any] = {}
    strong_count = 0
    weak_count = 0
    neutral_count = 0
    pct_sum = 0.0
    vol_sum = 0.0
    vol_weighted_num = 0.0

    for item in opening_data:
        code = item.get('code', 'unknown')
        name = item.get('name', 'Unknown')
        try:
            from plugins.utils.index_pct_sanity import reconcile_index_change_pct

            op = item.get("open_price") or item.get("opening_price")
            pc = item.get("close_yesterday") or item.get("pre_close")
            raw_cp = item.get("change_pct")
            rcp = reconcile_index_change_pct(raw_cp, op, pc)
            pick = rcp if rcp is not None else raw_cp
            change_pct = float(pick) if pick is not None else 0.0
        except Exception:
            try:
                change_pct = float(item.get("change_pct", 0) or 0)
            except (TypeError, ValueError):
                change_pct = 0.0
        volume = float(item.get('volume', 0) or 0)

        pct_sum += change_pct
        if volume > 0:
            vol_sum += volume
            vol_weighted_num += change_pct * volume

        if change_pct > 1.0:
            strength = "强"
            strength_score = 0.8
            strong_count += 1
        elif change_pct > 0.3:
            strength = "偏强"
            strength_score = 0.5
            strong_count += 1
        elif change_pct > -0.3:
            strength = "中性"
            strength_score = 0.0
            neutral_count += 1
        elif change_pct > -1.0:
            strength = "偏弱"
            strength_score = -0.5
            weak_count += 1
        else:
            strength = "弱"
            strength_score = -0.8
            weak_count += 1

        gap_pct = change_pct
        entry: Dict[str, Any] = {
            'name': name,
            'change_pct': change_pct,
            'gap_pct': gap_pct,
            'volume': volume,
            'strength': strength,
            'strength_score': strength_score,
        }

        intraday_adjusted = False
        try:
            from src.data_collector import fetch_index_opening_history

            hist_df = fetch_index_opening_history(str(code), lookback_days=lookback)
            if hist_df is not None and not hist_df.empty:
                vol_col = None
                for col in ('成交量', 'volume', 'vol'):
                    if col in hist_df.columns:
                        vol_col = col
                        break
                if vol_col:
                    mean_vol = float(hist_df[vol_col].mean())
                    if mean_vol > 0 and volume > 0:
                        entry['vol_vs_opening_avg'] = round(volume / mean_vol, 4)
                        intraday_adjusted = True
        except Exception:
            pass

        entry['intraday_adjusted'] = intraday_adjusted
        index_analysis[code] = entry

    n = len(opening_data)
    equal_weighted_sentiment = round(pct_sum / n, 4) if n else 0.0
    volume_weighted_sentiment = (
        round(vol_weighted_num / vol_sum, 4) if vol_sum > 0 and include_vol_weighted else None
    )

    total_count = strong_count + weak_count
    if total_count > 0:
        sentiment_score = (strong_count - weak_count) / total_count
    else:
        sentiment_score = 0.0

    if sentiment_score > 0.5:
        market_sentiment = "强势"
    elif sentiment_score > 0:
        market_sentiment = "偏强"
    elif sentiment_score > -0.5:
        market_sentiment = "中性"
    elif sentiment_score > -1:
        market_sentiment = "偏弱"
    else:
        market_sentiment = "弱势"

    sector_heat_summary = ""
    try:
        from plugins.data_collection.limit_up.sector_heat import tool_sector_heat_score

        sh = tool_sector_heat_score()
        if isinstance(sh, dict) and sh.get("success") and not sh.get("error"):
            sector_heat_summary = _sector_heat_summary_line(sh)
    except Exception:
        pass

    summary: Dict[str, Any] = {
        'strong_count': strong_count,
        'weak_count': weak_count,
        'sentiment_score': sentiment_score,
        'market_sentiment': market_sentiment,
        'timestamp': opening_data[0].get('timestamp', '') if opening_data else '',
        'equal_weighted_sentiment': equal_weighted_sentiment,
        'volume_weighted_note': (
            '各指数成交量量级不可比，大盘指数权重大，仅供参考'
            if volume_weighted_sentiment is not None
            else ''
        ),
    }
    if volume_weighted_sentiment is not None:
        summary['volume_weighted_sentiment'] = volume_weighted_sentiment
    if sector_heat_summary:
        summary['sector_heat_summary'] = sector_heat_summary

    any_vol_hist = any(
        isinstance(v, dict) and v.get('intraday_adjusted') for v in index_analysis.values()
    )
    summary['aggregate_intraday_adjusted'] = bool(any_vol_hist)
    summary['neutral_count'] = neutral_count
    summary['total_count'] = n

    # 与 analyze_opening_market 一致：顶层为各指数 code 条目 + summary，便于落盘与 report_meta
    out: Dict[str, Any] = dict(index_analysis)
    out['summary'] = summary
    return out


def tool_analyze_opening_market(**kwargs: Any) -> Dict[str, Any]:
    """OpenClaw 工具：开盘分析"""
    if kwargs:
        logger.debug("tool_analyze_opening_market: ignoring kwargs %s", sorted(kwargs.keys()))
    return trend_analysis(analysis_type="opening_market")
