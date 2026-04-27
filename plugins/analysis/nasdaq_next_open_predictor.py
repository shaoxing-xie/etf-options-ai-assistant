"""
次日开盘方向预测（规则驱动、无训练）。

目标（binary）：
- direction: 次交易日开盘相对“今日收盘基准”的涨/跌方向

说明：
- 在 14:30 尾盘任务中，真实“收盘价”尚未可得时，使用 latest_price 作为 close proxy，
  并将质量标记为 degraded（避免口径漂移与误导）。
- Phase A/B：Layer2 相似日仅用 NQ/代理序列，不引入 ETF 侧字段（避免 report_data 依赖不稳定）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _sigmoid(x: float) -> float:
    # avoid import math for tiny helper
    if x >= 0:
        z = pow(2.718281828459045, -x)
        return 1.0 / (1.0 + z)
    z = pow(2.718281828459045, x)
    return z / (1.0 + z)


def _parse_trade_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(s or "").strip(), "%Y-%m-%d")
    except Exception:
        return None


def _cosine_sim(a: List[float], b: List[float]) -> Optional[float]:
    if len(a) != len(b) or not a:
        return None
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return None
    return dot / ((na**0.5) * (nb**0.5))


def _extract_etf_klines(report_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    # tool_fetch_etf_historical: {"success": True, "data": {"klines": [...]}} (or list form)
    res = report_data.get("tool_fetch_etf_historical")
    if not isinstance(res, dict) or not res.get("success"):
        return []
    data = res.get("data")
    if isinstance(data, dict) and isinstance(data.get("klines"), list):
        return [x for x in data["klines"] if isinstance(x, dict)]
    if isinstance(data, list) and data and isinstance(data[0], dict):
        block = data[0]
        if isinstance(block.get("klines"), list):
            return [x for x in block["klines"] if isinstance(x, dict)]
    return []


def _calc_close_to_next_open_labels(klines: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    返回 {trade_date: label}，label=1 表示 next_open >= close_of_trade_date else 0。
    依赖日线 kline 至少包含 date/open/close。
    """
    out: Dict[str, int] = {}
    rows: List[Tuple[str, Optional[float], Optional[float]]] = []
    for r in klines:
        td = str(r.get("date") or r.get("trade_date") or r.get("day") or "").strip()
        if not td:
            continue
        o = _safe_float(r.get("open"))
        c = _safe_float(r.get("close"))
        rows.append((td, o, c))
    # ensure ascending by date
    rows.sort(key=lambda x: x[0])
    for i in range(len(rows) - 1):
        td, _, c = rows[i]
        next_td, next_o, _ = rows[i + 1]
        if c is None or next_o is None:
            continue
        out[td] = 1 if float(next_o) >= float(c) else 0
    return out


def _percentile_score(hist: List[float], current: Optional[float]) -> Optional[float]:
    if current is None:
        return None
    arr = sorted([x for x in hist if x is not None])
    if len(arr) < 5:
        return None
    le = sum(1 for x in arr if x <= float(current))
    pct = (le / len(arr)) * 100.0
    return _clip((pct - 50.0) / 50.0, -1.0, 1.0)


def _momentum_score_robust(hist: List[float], current: Optional[float]) -> Optional[float]:
    """
    Layer1 动量映射（抗饱和）：
    - 用稳健 z-score: (x - median) / IQR
    - 用 tanh 压缩尾部，避免轻易顶到 1.0
    """
    if current is None:
        return None
    arr = sorted([float(x) for x in hist if x is not None])
    if len(arr) < 8:
        return None
    n = len(arr)
    med = arr[n // 2] if n % 2 == 1 else 0.5 * (arr[n // 2 - 1] + arr[n // 2])
    q1 = arr[int(0.25 * (n - 1))]
    q3 = arr[int(0.75 * (n - 1))]
    iqr = float(q3 - q1)
    if iqr <= 1e-9:
        # 回退分位方案
        return _percentile_score(arr, current)
    z = (float(current) - med) / iqr
    # tanh 软压缩：z=2 对应约 0.76；z=4 对应约 0.96
    t = (pow(2.718281828459045, z) - pow(2.718281828459045, -z)) / (
        pow(2.718281828459045, z) + pow(2.718281828459045, -z)
    )
    return _clip(0.85 * t, -1.0, 1.0)


@dataclass
class NextOpenPredictorConfig:
    lookback_days: int = 60
    min_backtest_n: int = 20
    nn_topk: int = 20
    weekend_penalty: float = 0.7
    alpha: float = 1.0
    weights: Tuple[float, float] = (0.5, 0.3)  # Layer1, Layer2; Layer3 is gate


def _fit_alpha_platt(scores: List[float], labels: List[float]) -> Tuple[Optional[float], Optional[float]]:
    """
    一元 Platt-like 校准：只拟合 alpha（无截距）以最小化 Brier。
    返回 (alpha, brier)；数据不足时返回 (None, None)。
    """
    if len(scores) < 20 or len(scores) != len(labels):
        return None, None
    best_alpha = None
    best_brier = None
    # coarse-to-fine grid
    for alpha in [0.5, 0.8, 1.0, 1.2, 1.5, 1.8, 2.2, 2.8, 3.5]:
        b = 0.0
        for s, y in zip(scores, labels):
            p = _sigmoid(float(alpha) * float(s))
            b += (p - y) * (p - y)
        b /= float(len(scores))
        if best_brier is None or b < best_brier:
            best_brier = b
            best_alpha = float(alpha)
    return best_alpha, best_brier


def _score_for_event(
    e: Dict[str, Any],
    *,
    hist_mom: List[float],
    labels: Dict[str, int],
    events_pool: List[Dict[str, Any]],
    klines: List[Dict[str, Any]],
    cfg: NextOpenPredictorConfig,
) -> Optional[Tuple[float, float]]:
    """
    返回 (score_s, y)。
    - score_s 为未校准的融合分数 s
    - y 为真实 label (0/1)
    """
    td = str(e.get("trade_date") or e.get("date") or "").strip()
    if not td or td not in labels:
        return None
    a0 = e.get("analysis") if isinstance(e.get("analysis"), dict) else {}
    fr0 = a0.get("futures_reference") if isinstance(a0.get("futures_reference"), dict) else {}
    m0 = _safe_float(fr0.get("change_pct")) or _safe_float(a0.get("index_day_ret_pct"))
    i0 = _safe_float(a0.get("index_day_ret_pct"))
    momentum_score = _percentile_score(hist_mom, m0) or 0.0
    today_vec = [float(m0 or 0.0), float(i0 or 0.0)]

    # similarity vs prior pool (avoid leakage): only compare with events strictly before td
    sims: List[Tuple[float, float, str, int, float]] = []
    for h in events_pool:
        td_h = str(h.get("trade_date") or h.get("date") or "").strip()
        if not td_h or td_h >= td or td_h not in labels:
            continue
        a1 = h.get("analysis") if isinstance(h.get("analysis"), dict) else {}
        fr1 = a1.get("futures_reference") if isinstance(a1.get("futures_reference"), dict) else {}
        m1 = _safe_float(fr1.get("change_pct")) or _safe_float(a1.get("index_day_ret_pct"))
        i1 = _safe_float(a1.get("index_day_ret_pct"))
        vec1 = [float(m1 or 0.0), float(i1 or 0.0)]
        sim = _cosine_sim(today_vec, vec1)
        if sim is None:
            continue
        # weekend penalty: check kline calendar day gap
        gap_days = 1.0
        dt_td = _parse_trade_date(td_h)
        if dt_td is not None:
            dates = sorted({str(r.get("date") or "").strip() for r in klines if str(r.get("date") or "").strip()})
            if td_h in dates:
                idx = dates.index(td_h)
                if idx + 1 < len(dates):
                    dt_next = _parse_trade_date(dates[idx + 1])
                    if dt_next is not None:
                        gap_days = float((dt_next - dt_td).days)
        w = 1.0 * (float(cfg.weekend_penalty) if gap_days > 1.5 else 1.0)
        sims.append((float(sim), w, td_h, int(labels[td_h]), gap_days))
    sims.sort(key=lambda x: x[0], reverse=True)
    top = sims[: max(1, int(cfg.nn_topk))]
    w_sum = sum(w for _, w, *_ in top) or 0.0
    p_up_nn = None
    if w_sum > 0:
        p_up_nn = sum(w * float(lbl) for _, w, _, lbl, _ in top) / w_sum
    corr_score = (2.0 * float(p_up_nn) - 1.0) if p_up_nn is not None else 0.0

    w1, w2 = cfg.weights
    s = float(w1) * float(momentum_score) + float(w2) * float(corr_score)
    y = float(labels[td])
    return s, y


def _load_recent_monitor_events(lookback_days: int = 60) -> List[Dict[str, Any]]:
    root = Path(__file__).resolve().parents[2] / "data" / "semantic" / "nasdaq_513300_monitor_events"
    if not root.exists():
        return []
    rows: List[Dict[str, Any]] = []
    # each file is YYYY-MM-DD.jsonl, each line is an event
    for p in sorted(root.glob("*.jsonl"), reverse=True):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
        except Exception:
            continue
        if len(rows) >= lookback_days * 6:
            break
    return rows


def _persist_jsonl(dir_rel: str, trade_date: str, row: Dict[str, Any]) -> None:
    td = str(trade_date or "").strip()
    if not td:
        return
    base = Path(__file__).resolve().parents[2] / dir_rel
    base.mkdir(parents=True, exist_ok=True)
    p = base / f"{td}.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _persist_json(dir_rel: str, trade_date: str, monitor_point: str, obj: Dict[str, Any]) -> None:
    td = str(trade_date or "").strip()
    mp = str(monitor_point or "").strip().upper()
    if not td or not mp:
        return
    base = Path(__file__).resolve().parents[2] / dir_rel
    base.mkdir(parents=True, exist_ok=True)
    p = base / f"{td}_{mp}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_tavily_event_signal(trade_date: str) -> Dict[str, Any]:
    """
    事件信号源1：Tavily（新闻检索）。
    返回:
    - success: 是否成功完成检索
    - event_risk: [0,1]
    - note: 简短说明
    - events: 提取的事件标签
    """
    try:
        from plugins.utils.tavily_client import tavily_search_with_include_domain_fallback
    except Exception as e:
        return {"success": False, "event_risk": 0.0, "note": f"tavily_import_error:{type(e).__name__}", "events": []}

    query = (
        "Nasdaq 100 overnight risk events in next 24 hours: "
        "US mega-cap earnings after market close (AAPL MSFT NVDA AMZN GOOGL META TSLA), "
        "and macro events (CPI FOMC NFP PCE Fed speech). List event names and timing."
    )
    try:
        res = tavily_search_with_include_domain_fallback(
            query,
            topic="news",
            days=3,
            deep=True,
            max_results=8,
        )
    except Exception as e:
        return {"success": False, "event_risk": 0.0, "note": f"tavily_query_error:{type(e).__name__}", "events": []}

    if not isinstance(res, dict) or not res.get("success"):
        return {"success": False, "event_risk": 0.0, "note": str((res or {}).get("message") or "tavily_failed"), "events": []}

    raw = res.get("raw") if isinstance(res.get("raw"), dict) else {}
    chunks: List[str] = []
    ans = str(res.get("answer") or "").strip()
    if ans:
        chunks.append(ans)
    results = raw.get("results") if isinstance(raw.get("results"), list) else []
    for r in results[:8]:
        if not isinstance(r, dict):
            continue
        chunks.append(str(r.get("title") or ""))
        chunks.append(str(r.get("content") or r.get("snippet") or ""))
    text = " ".join(chunks).lower()

    events: List[str] = []
    risk = 0.0
    # 宏观高影响优先
    if re.search(r"\bfomc\b|federal reserve|fed meeting", text):
        events.append("FOMC/FED")
        risk = max(risk, 0.55)
    if re.search(r"\bcpi\b|inflation", text):
        events.append("CPI")
        risk = max(risk, 0.50)
    if re.search(r"\bnfp\b|nonfarm payroll", text):
        events.append("NFP")
        risk = max(risk, 0.50)
    if re.search(r"\bpce\b", text):
        events.append("PCE")
        risk = max(risk, 0.45)

    # 科技权重股财报
    ticker_hits = 0
    for tk in ("aapl", "msft", "nvda", "amzn", "googl", "meta", "tsla"):
        if re.search(rf"\b{tk}\b", text):
            ticker_hits += 1
    if "earnings" in text and ticker_hits > 0:
        events.append(f"mega_cap_earnings:{ticker_hits}")
        risk = max(risk, min(0.35 + 0.03 * ticker_hits, 0.55))

    note = "tavily_ok_no_high_impact"
    if events:
        note = f"tavily_events:{','.join(events[:4])}"
    return {"success": True, "event_risk": _clip(risk, 0.0, 1.0), "note": note, "events": events[:8]}


def _fetch_yf_event_signal(trade_date: str) -> Dict[str, Any]:
    """
    事件信号源2：yfinance（mega-cap 财报日期）。
    仅判断是否处于隔夜窗口附近，不做方向判断。
    """
    try:
        import pandas as pd  # type: ignore
        import yfinance as yf  # type: ignore
    except Exception as e:
        return {"success": False, "event_risk": 0.0, "note": f"yf_import_error:{type(e).__name__}", "events": []}

    td = _parse_trade_date(trade_date)
    if td is None:
        td = datetime.utcnow()
    # 以自然日近似隔夜窗口（trade_date 当天及次日）
    d0 = td.date()
    d1 = (td.date()).fromordinal(td.date().toordinal() + 1)

    symbols = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA")
    events: List[str] = []
    err_count = 0

    for s in symbols:
        try:
            t = yf.Ticker(s)
            dt = None
            src = None
            cal = getattr(t, "calendar", None)
            if cal is not None and hasattr(cal, "index") and len(cal.index) > 0:
                idx = [str(x) for x in cal.index]
                if "Earnings Date" in idx:
                    try:
                        val = cal.loc["Earnings Date"][0]
                        dt = pd.to_datetime(val, utc=True, errors="coerce")
                        src = "calendar"
                    except Exception:
                        dt = None
            if dt is None:
                ed = getattr(t, "earnings_dates", None)
                if ed is not None and hasattr(ed, "index") and len(ed.index) > 0:
                    try:
                        dt = pd.to_datetime(ed.index[0], utc=True, errors="coerce")
                        src = "earnings_dates"
                    except Exception:
                        dt = None
            if dt is None or str(dt) == "NaT":
                continue
            day = dt.date()
            if day in (d0, d1):
                events.append(f"{s}:{str(day)}:{src}")
        except Exception:
            err_count += 1
            continue

    if not events and err_count >= len(symbols):
        return {"success": False, "event_risk": 0.0, "note": "yf_all_failed_or_rate_limited", "events": []}

    risk = 0.0
    if events:
        # 单个 mega-cap 财报就足以提高隔夜不确定性
        risk = min(0.35 + 0.04 * len(events), 0.60)
    note = "yf_ok_no_near_earnings" if not events else f"yf_near_earnings:{len(events)}"
    return {"success": True, "event_risk": _clip(risk, 0.0, 1.0), "note": note, "events": events[:10]}


def _llm_fuse_probability(
    *,
    momentum_score: float,
    corr_score: float,
    event_risk: float,
    p_up_rule_raw: float,
    tav_sig: Dict[str, Any],
    yf_sig: Dict[str, Any],
) -> Dict[str, Any]:
    """
    可选 LLM 融合层：
    - 输入：结构化分数 + 事件摘要（非结构化抽取后的结构）
    - 输出：p_up_raw_llm（未校准概率）
    失败时返回 success=False，不阻断主流程。
    """
    try:
        from plugins.utils.llm_structured_extract import llm_json_from_unstructured
    except Exception as e:
        return {"success": False, "note": f"llm_import_error:{type(e).__name__}"}

    payload = {
        "features": {
            "momentum_score": round(float(momentum_score), 6),
            "similarity_score": round(float(corr_score), 6),
            "event_risk": round(float(event_risk), 6),
            "rule_p_up_raw": round(float(p_up_rule_raw), 6),
        },
        "event_sources": {
            "tavily_note": str((tav_sig or {}).get("note") or ""),
            "tavily_events": (tav_sig or {}).get("events") or [],
            "yfinance_note": str((yf_sig or {}).get("note") or ""),
            "yfinance_events": (yf_sig or {}).get("events") or [],
        },
    }
    extraction_prompt = (
        "你是量化预测融合器。基于给定结构化特征与事件摘要，输出 JSON。"
        "要求：仅输出 JSON；不要解释。"
        "字段："
        "{\"p_up_raw\": number, \"confidence\": \"low|medium|high\", \"rationale\": string}。"
        "约束：p_up_raw 取值 [0.01,0.99]；当 event_risk 较高时概率向 0.5 收缩。"
    )
    res = llm_json_from_unstructured(
        raw_text=json.dumps(payload, ensure_ascii=False),
        extraction_prompt=extraction_prompt,
        profile="default",
    )
    if not isinstance(res, dict) or not res.get("success"):
        return {"success": False, "note": str((res or {}).get("message") or "llm_failed")}
    data = res.get("data")
    if not isinstance(data, dict):
        return {"success": False, "note": "llm_non_dict"}
    p = _safe_float(data.get("p_up_raw"))
    if p is None:
        return {"success": False, "note": "llm_missing_p"}
    p = _clip(float(p), 0.01, 0.99)
    return {
        "success": True,
        "p_up_raw": p,
        "confidence": str(data.get("confidence") or "").strip().lower() or "medium",
        "rationale": str(data.get("rationale") or "").strip()[:280],
        "model_meta": (res.get("meta") if isinstance(res.get("meta"), dict) else {}),
    }


def predict_next_open_direction(
    report_data: Dict[str, Any],
    *,
    cfg: Optional[NextOpenPredictorConfig] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    cfg = cfg or NextOpenPredictorConfig()

    market_profile = str(report_data.get("market_profile") or "")
    monitor_point = str((report_data.get("monitor_context") or {}).get("monitor_point") or report_data.get("monitor_point") or "M7")
    trade_date = str(report_data.get("trade_date") or report_data.get("date") or "").strip()
    generated_at = str(report_data.get("generated_at") or "").strip()
    run_id = str((report_data.get("_meta") or {}).get("run_id") or f"next_open-{trade_date}-{monitor_point}")
    task_id = str((report_data.get("_meta") or {}).get("task_id") or "etf-nasdaq-close-513300")

    quality_status = "ok"
    degraded_reason: Optional[str] = None

    # ---------- inputs ----------
    ana = report_data.get("analysis") if isinstance(report_data.get("analysis"), dict) else {}
    # proxy momentum input (Phase A): use NQ futures change_pct when available; else fall back to index_day_ret_pct
    futures_ref = ana.get("futures_reference") if isinstance(ana.get("futures_reference"), dict) else {}
    nq_change_pct = _safe_float(futures_ref.get("change_pct"))
    idx_ret_pct = _safe_float(ana.get("index_day_ret_pct"))
    momentum_pct = nq_change_pct if nq_change_pct is not None else idx_ret_pct

    # close proxy (14:30 has no real close)
    latest_price = _safe_float((report_data.get("tail_session_snapshot") or {}).get("latest_price"))
    if latest_price is None:
        quality_status = "degraded"
        degraded_reason = "PREDICTOR_NO_LATEST_PRICE"

    # ---------- Layer1 momentum score ----------
    # build historical momentum list from recent monitor events
    hist_events = _load_recent_monitor_events(lookback_days=cfg.lookback_days)
    hist_mom: List[float] = []
    for e in hist_events:
        a0 = e.get("analysis") if isinstance(e.get("analysis"), dict) else {}
        fr0 = a0.get("futures_reference") if isinstance(a0.get("futures_reference"), dict) else {}
        m0 = _safe_float(fr0.get("change_pct"))
        if m0 is None:
            m0 = _safe_float(a0.get("index_day_ret_pct"))
        if m0 is not None:
            hist_mom.append(float(m0))
    momentum_score = _momentum_score_robust(hist_mom, momentum_pct)
    if momentum_score is None:
        momentum_score = 0.0
        quality_status = "degraded"
        degraded_reason = degraded_reason or "PREDICTOR_INSUFFICIENT_HISTORY"

    # ---------- Layer2 similarity (topK conditional probability) ----------
    # feature vector: [momentum_pct_proxy, idx_ret_pct_proxy]
    today_vec = [float(momentum_pct or 0.0), float(idx_ret_pct or 0.0)]
    klines = _extract_etf_klines(report_data)
    labels = _calc_close_to_next_open_labels(klines)

    sims: List[Tuple[float, float, str, int, float]] = []
    # (sim, weight, trade_date, label, gap_days)
    for e in hist_events:
        td = str(e.get("trade_date") or e.get("date") or "").strip()
        if not td or td not in labels:
            continue
        a0 = e.get("analysis") if isinstance(e.get("analysis"), dict) else {}
        fr0 = a0.get("futures_reference") if isinstance(a0.get("futures_reference"), dict) else {}
        m0 = _safe_float(fr0.get("change_pct"))
        if m0 is None:
            m0 = _safe_float(a0.get("index_day_ret_pct"))
        i0 = _safe_float(a0.get("index_day_ret_pct"))
        vec0 = [float(m0 or 0.0), float(i0 or 0.0)]
        sim = _cosine_sim(today_vec, vec0)
        if sim is None:
            continue
        # weekend/holiday penalty: if td->next_td spans >1 calendar day
        gap_days = 1.0
        dt_td = _parse_trade_date(td)
        # approximate next-day by scanning klines sorted and finding next row
        # if we can't compute, keep gap_days=1
        if dt_td is not None:
            # find next date in klines
            next_date = None
            for r in klines:
                d = str(r.get("date") or "").strip()
                if d == td:
                    # next element in sorted list is hard here; skip
                    continue
            # robust: compute by looking at all kline dates and picking next greater
            dates = sorted({str(r.get("date") or "").strip() for r in klines if str(r.get("date") or "").strip()})
            if td in dates:
                idx = dates.index(td)
                if idx + 1 < len(dates):
                    next_date = dates[idx + 1]
            if next_date:
                dt_next = _parse_trade_date(next_date)
                if dt_next is not None:
                    gap_days = float((dt_next - dt_td).days)
        w = 1.0
        if gap_days > 1.5:
            w *= float(cfg.weekend_penalty)
        sims.append((float(sim), w, td, int(labels[td]), gap_days))

    sims.sort(key=lambda x: x[0], reverse=True)
    top = sims[: max(1, int(cfg.nn_topk))]
    w_sum = sum(w for _, w, *_ in top) or 0.0
    p_up_nn = None
    if w_sum > 0:
        p_up_nn = sum(w * float(lbl) for _, w, _, lbl, _ in top) / w_sum
    corr_score = (2.0 * float(p_up_nn) - 1.0) if p_up_nn is not None else 0.0
    similarity_debug = {
        "topk_requested": int(cfg.nn_topk),
        "topk_used": len(top),
        "weighted_sum": round(float(w_sum), 6),
        "p_up_nn": round(float(p_up_nn), 6) if p_up_nn is not None else None,
        "top_matches": [
            {"trade_date": td, "sim": round(float(sim), 4), "label": int(lbl), "weight": round(float(w), 3), "gap_days": round(float(gd), 1)}
            for sim, w, td, lbl, gd in top[:5]
        ],
    }

    # ---------- Layer3 event gate (Tavily + yfinance 双源) ----------
    event_risk = 0.0
    event_note = "event_gate_default"
    tav_sig = _fetch_tavily_event_signal(trade_date)
    yf_sig = _fetch_yf_event_signal(trade_date)
    event_sources = {"tavily": tav_sig, "yfinance": yf_sig}
    src_ok = [k for k, v in event_sources.items() if isinstance(v, dict) and v.get("success")]
    if not src_ok:
        quality_status = "degraded"
        degraded_reason = degraded_reason or "PREDICTOR_EVENT_SOURCE_FAIL"
        event_note = "event_sources_unavailable"
    else:
        tav_risk = _safe_float((tav_sig or {}).get("event_risk")) or 0.0
        yf_risk = _safe_float((yf_sig or {}).get("event_risk")) or 0.0
        event_risk = max(tav_risk, yf_risk)
        event_note = ";".join(
            x for x in [str((tav_sig or {}).get("note") or ""), str((yf_sig or {}).get("note") or "")] if x
        )[:240]

    # ---------- backtest stats (rolling 60) + alpha calibration ----------
    w1, w2 = cfg.weights
    dates_sorted = sorted(labels.keys())
    recent_dates = dates_sorted[-cfg.lookback_days :] if dates_sorted else []

    # Build (s, y) pairs using leakage-safe pool (prior events only).
    events_by_date = []
    for e in hist_events:
        td0 = str(e.get("trade_date") or e.get("date") or "").strip()
        if td0:
            events_by_date.append((td0, e))
    events_by_date.sort(key=lambda x: x[0])

    sy_scores: List[float] = []
    sy_labels: List[float] = []
    for td0, e in events_by_date:
        if td0 not in recent_dates:
            continue
        scored = _score_for_event(e, hist_mom=hist_mom, labels=labels, events_pool=hist_events, klines=klines, cfg=cfg)
        if scored is None:
            continue
        s0, y0 = scored
        sy_scores.append(float(s0))
        sy_labels.append(float(y0))

    alpha_fit, brier_fit = _fit_alpha_platt(sy_scores, sy_labels)
    alpha_used = float(alpha_fit) if alpha_fit is not None else float(cfg.alpha)

    # ---------- fuse for today ----------
    s = float(w1) * float(momentum_score) + float(w2) * float(corr_score)
    p_up_raw = _sigmoid(alpha_used * s)

    # LLM 融合（可选，失败不阻断）
    llm_fusion = _llm_fuse_probability(
        momentum_score=float(momentum_score),
        corr_score=float(corr_score),
        event_risk=float(event_risk),
        p_up_rule_raw=float(p_up_raw),
        tav_sig=tav_sig,
        yf_sig=yf_sig,
    )
    p_up_raw_source = "rule"
    if isinstance(llm_fusion, dict) and llm_fusion.get("success"):
        p_up_raw = float(llm_fusion.get("p_up_raw"))
        p_up_raw_source = "llm_fused"

    p_up_pre_gate = float(p_up_raw)
    p_up = 0.5 + (1.0 - float(event_risk)) * (p_up_pre_gate - 0.5)
    p_up = _clip(float(p_up), 0.001, 0.999)

    direction = "up" if p_up >= 0.5 else "down"
    direction_prob = max(p_up, 1.0 - p_up)

    # evaluate backtest with alpha_used
    n = len(sy_scores)
    hit = 0
    brier_sum = 0.0
    for s0, y0 in zip(sy_scores, sy_labels):
        p0 = _sigmoid(alpha_used * float(s0))
        pred = 1.0 if p0 >= 0.5 else 0.0
        hit += 1 if pred == float(y0) else 0
        brier_sum += (p0 - float(y0)) * (p0 - float(y0))

    hit_rate = (hit / n) if n > 0 else None
    brier = (brier_sum / n) if n > 0 else None
    coverage = (n / float(len(recent_dates))) if recent_dates else None
    backtest_stats = {
        "hit_rate_60d": round(hit_rate, 4) if hit_rate is not None and n >= cfg.min_backtest_n else None,
        "brier_60d": round(brier, 4) if brier is not None and n >= cfg.min_backtest_n else None,
        "n_60d": int(n),
        "coverage_60d": round(coverage, 4) if coverage is not None else None,
        "window_start": recent_dates[0] if recent_dates else None,
        "window_end": recent_dates[-1] if recent_dates else None,
        "calibration_curve": "platt" if alpha_fit is not None else "none",
        "alpha": round(alpha_used, 4),
        "brier_fit": round(float(brier_fit), 4) if brier_fit is not None else None,
    }

    confidence_level = "high"
    if quality_status == "degraded" or (n < cfg.min_backtest_n):
        confidence_level = "low" if n < cfg.min_backtest_n else "medium"
    elif event_risk >= 0.45:
        confidence_level = "medium"

    feature_row = {
        "_meta": {
            "schema_name": "nasdaq_513300_next_open_predictor_features",
            "schema_version": "1.0.0",
            "task_id": task_id,
            "run_id": run_id,
            "data_layer": "L2",
            "generated_at": generated_at,
            "trade_date": trade_date,
            "source_tools": ["tool_fetch_etf_data", "tool_fetch_index_data"],
            "lineage_refs": [f"monitor_point:{monitor_point}"],
            "quality_status": quality_status,
        },
        "market_profile": market_profile,
        "monitor_point": monitor_point,
        "momentum": {"momentum_pct": momentum_pct, "score": momentum_score, "hist_n": len(hist_mom)},
        "similarity": {
            "p_up_nn": round(float(p_up_nn), 4) if p_up_nn is not None else None,
            "score": round(float(corr_score), 4),
            "topk": int(cfg.nn_topk),
            "debug": similarity_debug,
        },
        "event_gate": {"event_risk": event_risk, "event_note": event_note, "sources": event_sources},
        "inputs": {"idx_ret_pct": idx_ret_pct, "nq_change_pct": nq_change_pct, "latest_price_proxy_close": latest_price},
        "calibration": {"alpha_used": alpha_used, "method": "platt" if alpha_fit is not None else "none"},
        "llm_fusion": {
            "enabled": True,
            "success": bool((llm_fusion or {}).get("success")),
            "source": p_up_raw_source,
            "p_up_raw": round(float(p_up_raw), 6),
            "confidence": (llm_fusion or {}).get("confidence"),
            "rationale": (llm_fusion or {}).get("rationale"),
            "note": (llm_fusion or {}).get("note"),
            "model_meta": (llm_fusion or {}).get("model_meta"),
        },
    }

    decision_row = {
        "_meta": {
            "schema_name": "nasdaq_513300_next_open_direction_event",
            "schema_version": "1.0.0",
            "task_id": task_id,
            "run_id": run_id,
            "data_layer": "L3",
            "generated_at": generated_at,
            "trade_date": trade_date,
            "source_tools": ["nasdaq_next_open_predictor"],
            "lineage_refs": [f"features_run_id:{run_id}", f"monitor_point:{monitor_point}"],
            "quality_status": quality_status,
        },
        "market_profile": market_profile,
        "monitor_point": monitor_point,
        "direction": direction,
        "p_up": round(p_up, 4),
        "direction_prob": round(float(direction_prob), 4),
        "confidence_level": confidence_level,
        "components": [
            {"layer": "layer1_momentum", "score": round(float(momentum_score), 4), "weight": float(w1), "contribution": round(float(w1) * float(momentum_score), 4)},
            {"layer": "layer2_similarity", "score": round(float(corr_score), 4), "weight": float(w2), "contribution": round(float(w2) * float(corr_score), 4)},
            {"layer": "layer3_event_gate", "event_risk": round(float(event_risk), 4)},
            {"layer": "layer4_llm_fusion", "source": p_up_raw_source, "p_up_raw": round(float(p_up_raw), 4)},
        ],
        "llm_fusion": {
            "source": p_up_raw_source,
            "success": bool((llm_fusion or {}).get("success")),
            "p_up_raw": round(float(p_up_raw), 6),
            "p_up_pre_gate": round(float(p_up_pre_gate), 6),
            "confidence": (llm_fusion or {}).get("confidence"),
            "rationale": (llm_fusion or {}).get("rationale"),
            "note": (llm_fusion or {}).get("note"),
        },
        "backtest_stats": backtest_stats,
        "probability_debug": {
            "p_up_raw_pre_gate": round(float(p_up_pre_gate), 6),
            "event_risk": round(float(event_risk), 6),
            "p_up_final": round(float(p_up), 6),
        },
        "similarity_debug": similarity_debug,
        "event_sources": event_sources,
        "degraded_reason": degraded_reason,
    }

    semantic_view = {
        "_meta": {
            "schema_name": "nasdaq_513300_next_open_direction_semantic",
            "schema_version": "1.0.0",
            "generated_at": generated_at,
            "trade_date": trade_date,
        },
        "data": {
            "market_profile": market_profile,
            "monitor_point": monitor_point,
            "direction": direction,
            "p_up": round(p_up, 4),
            "direction_prob": round(float(direction_prob), 4),
            "confidence_level": confidence_level,
            "components": decision_row.get("components"),
            "backtest_stats": backtest_stats,
        },
    }

    if persist and trade_date:
        _persist_jsonl("data/feature/nasdaq_513300_next_open_predictor_features", trade_date, feature_row)
        _persist_jsonl("data/decision/nasdaq_513300_next_open_direction_events", trade_date, decision_row)
        _persist_json("data/semantic/nasdaq_513300_next_open_direction_view", trade_date, monitor_point, semantic_view)

    return {
        "success": True,
        "quality_status": quality_status,
        "feature": feature_row,
        "decision": decision_row,
        "semantic_view": semantic_view,
    }

