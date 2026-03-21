"""
交易助手统一入口（工具层）。

提供 tool_trading_copilot：把 “交易状态 → A股时段细分 → 快扫数据 → (条件触发) 信号 → 持仓检查”
压缩为一次工具调用，输出低上下文摘要。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz

from src.config_loader import load_system_config

from plugins.merged.fetch_index_data import tool_fetch_index_data
from plugins.merged.fetch_etf_data import tool_fetch_etf_data
from plugins.data_collection.futures.fetch_a50 import tool_fetch_a50_data
from plugins.data_collection.utils.check_trading_status import tool_check_trading_status
from plugins.data_collection.utils.a_share_market_regime import tool_get_a_share_market_regime
from src.signal_generation import tool_generate_signals

# 股票实时工具（用于持仓检查 / 可交易性过滤兜底）
from plugins.data_collection.stock.fetch_realtime import tool_fetch_stock_realtime

try:
    from plugins.notification.send_feishu_card_webhook import tool_send_feishu_card_webhook
    FEISHU_CARD_SEND_AVAILABLE = True
except Exception:
    FEISHU_CARD_SEND_AVAILABLE = False

    def tool_send_feishu_card_webhook(*args, **kwargs):  # type: ignore[no-redef]
        return {"success": False, "message": "tool_send_feishu_card_webhook unavailable", "data": None}


@dataclass(frozen=True)
class CopilotDefaults:
    timezone: str = "Asia/Shanghai"
    # 快扫核心指数（兜底）
    index_codes: Tuple[str, ...] = ("000001", "000300", "399006", "000905")
    # 快扫核心 ETF（兜底）
    etf_codes: Tuple[str, ...] = ("510300", "510500", "159915")
    # 情绪区间 -> 飞书卡片模板
    sentiment_templates: Tuple[Tuple[int, int, str], ...] = (
        (0, 30, "red"),
        (31, 50, "orange"),
        (51, 70, "yellow"),
        (71, 85, "blue"),
        (86, 100, "green"),
    )


def _now_shanghai(tz_name: str) -> datetime:
    tz = pytz.timezone(tz_name)
    return datetime.now(tz)


def _as_list(data: Any) -> List[Dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _compute_sentiment_score(index_rows: List[Dict[str, Any]]) -> int:
    """
    初版情绪分：用核心指数涨跌幅做一个可解释的 proxy。
    后续可引入成交额/广度/北向/波动等。
    """
    if not index_rows:
        return 50
    chgs = []
    for r in index_rows:
        # fetch_index_realtime 的字段名：change_percent
        chgs.append(_safe_float(r.get("change_percent"), 0.0))
    avg = sum(chgs) / max(1, len(chgs))
    score = 50.0 + avg * 8.0  # 1% ≈ 8 分
    return int(round(_clamp(score, 0, 100)))


def _sentiment_template(score: int) -> str:
    s = int(_clamp(float(score), 0, 100))
    for lo, hi, tpl in CopilotDefaults().sentiment_templates:
        if lo <= s <= hi:
            return tpl
    return "blue"


def _fmt_pct(x: Any) -> str:
    v = _safe_float(x, 0.0)
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%"


def _fmt_price(x: Any) -> str:
    v = _safe_float(x, 0.0)
    if v <= 0:
        return "—"
    # ETF/指数一般 2-6 位小数不统一，这里做保守展示
    if v < 10:
        return f"{v:.3f}"
    if v < 1000:
        return f"{v:.2f}"
    return f"{v:,.0f}"


def _sum_amount(rows: List[Dict[str, Any]]) -> float:
    total = 0.0
    for r in rows:
        # 不同源可能是 amount / 成交额
        total += _safe_float(r.get("amount") or r.get("成交额") or 0.0)
    return total


def _fetch_etf_amount_avg_5d(etf_code: str) -> Optional[float]:
    """
    尝试获取近 5 个交易日的日线成交额均值（用于量能因子）。
    若数据源不可用，返回 None。
    """
    # 简化：直接用 end_date 向前推 10 天
    try:
        from datetime import timedelta as _td

        now = _now_shanghai("Asia/Shanghai")
        end = now.strftime("%Y%m%d")
        start = (now - _td(days=10)).strftime("%Y%m%d")
    except Exception:
        start = None
        end = None

    try:
        hist = tool_fetch_etf_data(data_type="historical", etf_code=etf_code, period="daily", start_date=start, end_date=end)
        if not hist.get("success") or not hist.get("data"):
            return None
        data = hist.get("data")
        rows = _as_list(data)
        # 兼容：有些实现返回 {data: {bars:[...]}}
        if isinstance(data, dict) and "bars" in data:
            rows = _as_list(data.get("bars"))
        if not rows:
            return None
        # 取最后 5 条
        last = rows[-5:]
        amts = [_safe_float(r.get("amount") or r.get("成交额") or 0.0) for r in last]
        amts = [a for a in amts if a > 0]
        if not amts:
            return None
        return sum(amts) / len(amts)
    except Exception:
        return None


def _compute_sentiment_score_v2(
    *,
    index_rows: List[Dict[str, Any]],
    etf_rows: List[Dict[str, Any]],
    a50_change_pct: Optional[float],
    etf_amount_avg_5d: Optional[float],
) -> Dict[str, Any]:
    """
    情绪评分 v2（按 market-quick-scan 的 4 因子思想做“可退化”实现）：
    - 指数涨跌（proxy）
    - 成交额 vs 5日均量（用 ETF 成交额 proxy）
    - 北向资金（当前无数据源，跳过）
    - A50 期指（若有）
    """
    factors: Dict[str, Any] = {}

    # 1) 指数涨跌：用核心指数平均涨跌幅映射到 [-25,25]
    if index_rows:
        chgs = [_safe_float(r.get("change_percent"), 0.0) for r in index_rows]
        avg = sum(chgs) / max(1, len(chgs))
        idx_score = _clamp(avg * 8.0, -25.0, 25.0)
        factors["index_score"] = idx_score
        factors["index_avg_pct"] = avg
    else:
        factors["index_score"] = None

    # 2) 量能：用 ETF 成交额 vs 5日均值映射到 [-25,25]
    cur_amt = _sum_amount(etf_rows) if etf_rows else 0.0
    if cur_amt > 0 and etf_amount_avg_5d and etf_amount_avg_5d > 0:
        # ratio: (cur - avg)/avg
        ratio = (cur_amt - etf_amount_avg_5d) / etf_amount_avg_5d
        amt_score = _clamp(ratio * 25.0, -25.0, 25.0)
        factors["amount_score"] = amt_score
        factors["amount_ratio_vs_5d"] = ratio
        factors["amount_current"] = cur_amt
        factors["amount_avg_5d"] = etf_amount_avg_5d
    else:
        factors["amount_score"] = None
        factors["amount_current"] = cur_amt if cur_amt > 0 else None
        factors["amount_avg_5d"] = etf_amount_avg_5d

    # 3) 北向资金：暂无
    factors["northbound_score"] = None

    # 4) A50：映射到 [-25,25]
    if a50_change_pct is not None:
        a50_score = _clamp(float(a50_change_pct) * 8.0, -25.0, 25.0)
        factors["a50_score"] = a50_score
        factors["a50_change_pct"] = float(a50_change_pct)
    else:
        factors["a50_score"] = None

    usable = [v for k, v in factors.items() if k.endswith("_score") and isinstance(v, (int, float))]
    if not usable:
        return {"score": 50, "factors": factors, "note": "insufficient_factors"}
    raw = 50.0 + sum(float(x) for x in usable) / len(usable)
    return {"score": int(round(_clamp(raw, 0, 100))), "factors": factors, "note": None}


def _build_feishu_copilot_card(
    *,
    ts: str,
    sentiment_score: int,
    trading_status_cn: str,
    phase: Optional[str],
    indices: List[Dict[str, Any]],
    etfs: List[Dict[str, Any]],
    a50_spot: Optional[Dict[str, Any]],
    signal_brief: Optional[str],
    position_alerts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    tpl = _sentiment_template(sentiment_score)

    # 主要指数 fields（最多 4 个）
    idx_fields: List[Dict[str, Any]] = []
    for r in indices[:4]:
        name = str(r.get("name") or r.get("index_name") or r.get("code") or "").strip() or "指数"
        price = _fmt_price(r.get("current_price") or r.get("price"))
        pct = _fmt_pct(r.get("change_percent"))
        idx_fields.append(
            {
                "is_short": True,
                "text": {"tag": "lark_md", "content": f"**{name}**\n{price} ({pct})"},
            }
        )

    # ETF fields（最多 3 个）
    etf_fields: List[Dict[str, Any]] = []
    for r in etfs[:3]:
        name = str(r.get("name") or r.get("基金简称") or r.get("code") or "").strip() or str(r.get("code") or "")
        price = _fmt_price(r.get("current_price") or r.get("price"))
        pct = _fmt_pct(r.get("change_percent"))
        etf_fields.append(
            {
                "is_short": True,
                "text": {"tag": "lark_md", "content": f"**{name}**\n{price} ({pct})"},
            }
        )

    a50_line = ""
    if isinstance(a50_spot, dict) and a50_spot.get("current_price"):
        a50_line = f"**A50** { _fmt_price(a50_spot.get('current_price')) } ({ _fmt_pct(a50_spot.get('change_pct')) })"

    alert_line = ""
    if position_alerts:
        # 只显示前 2 条
        parts = []
        for a in position_alerts[:2]:
            sym = a.get("symbol")
            trig = a.get("trigger")
            parts.append(f"{sym}:{trig}")
        alert_line = " | ".join(parts)

    header_title = f"交易助手 - {ts}"
    subtitle = f"状态: {trading_status_cn}"
    if phase:
        subtitle += f" / {phase}"

    summary_lines = [f"**情绪**：{sentiment_score} 分"]
    if a50_line:
        summary_lines.append(a50_line)
    if signal_brief:
        summary_lines.append(f"**信号**：{signal_brief}")
    if alert_line:
        summary_lines.append(f"**持仓预警**：{alert_line}")

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": header_title},
                "template": tpl,
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**{subtitle}**"}},
                {"tag": "div", "fields": idx_fields} if idx_fields else {"tag": "div", "text": {"tag": "lark_md", "content": "_指数数据暂不可用_"}},
                {"tag": "div", "fields": etf_fields} if etf_fields else {"tag": "div", "text": {"tag": "lark_md", "content": "_ETF 数据暂不可用_"}},
                {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(summary_lines)}},
                {
                    "tag": "action",
                    "actions": [
                        {"tag": "button", "text": {"tag": "plain_text", "content": "快扫"}, "type": "default", "value": {"command": "/scan"}},
                        {"tag": "button", "text": {"tag": "plain_text", "content": "生成信号"}, "type": "primary", "value": {"command": "/signal"}},
                        {"tag": "button", "text": {"tag": "plain_text", "content": "检查持仓"}, "type": "default", "value": {"command": "/position"}},
                    ],
                },
            ],
        },
    }


def _load_positions(openclaw_workspace_dir: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    读取 openclaw workspace 的 positions.json（由 position-monitor 约定）。
    """
    positions_file = openclaw_workspace_dir / "memory" / "positions.json"
    if not positions_file.exists():
        return [], None
    try:
        raw = json.loads(positions_file.read_text(encoding="utf-8"))
        pos = raw.get("positions") if isinstance(raw, dict) else None
        if isinstance(pos, list):
            return [x for x in pos if isinstance(x, dict)], str(positions_file)
    except Exception:
        pass
    return [], str(positions_file)


def _fetch_symbol_price(symbol: str) -> Tuple[Optional[float], Optional[str]]:
    """
    获取单标的现价（ETF 或 A股股票）。
    """
    s = (symbol or "").strip()
    if not s:
        return None, None
    # 简单规则：ETF 通常 5/1 开头；股票 6/0/3/8/4 等
    try:
        if s.startswith(("5", "1")):
            r = tool_fetch_etf_data(data_type="realtime", etf_code=s)
            if r.get("success") and r.get("data"):
                d = r.get("data")
                if isinstance(d, dict):
                    return _safe_float(d.get("current_price") or d.get("price")), "etf"
                if isinstance(d, list) and d:
                    return _safe_float(d[0].get("current_price") or d[0].get("price")), "etf"
            return None, "etf"
        rr = tool_fetch_stock_realtime(stock_code=s)
        if rr.get("success") and rr.get("data"):
            d = rr.get("data")
            if isinstance(d, dict):
                return _safe_float(d.get("current_price") or d.get("price")), "stock"
            if isinstance(d, list) and d:
                return _safe_float(d[0].get("current_price") or d[0].get("price")), "stock"
        return None, "stock"
    except Exception:
        return None, None


def _check_positions(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    alerts: List[Dict[str, Any]] = []
    checked: List[Dict[str, Any]] = []

    for p in positions:
        symbol = str(p.get("symbol") or "").strip()
        if not symbol:
            continue
        current_price, kind = _fetch_symbol_price(symbol)
        if current_price is None or current_price <= 0:
            continue

        entry = _safe_float(p.get("entry_price"))
        qty = int(_safe_float(p.get("quantity"), 0))
        stop_loss = p.get("stop_loss")
        take_profit = p.get("take_profit")
        sl = _safe_float(stop_loss) if stop_loss is not None else None
        tp = _safe_float(take_profit) if take_profit is not None else None

        pnl = None
        pnl_pct = None
        if entry > 0:
            pnl = (current_price - entry) * qty
            pnl_pct = (current_price - entry) / entry * 100

        status = "ok"
        trigger = None
        if sl is not None and current_price <= sl:
            status = "triggered"
            trigger = "stop_loss"
        elif tp is not None and current_price >= tp:
            status = "triggered"
            trigger = "take_profit"

        checked.append(
            {
                "symbol": symbol,
                "kind": kind,
                "current_price": current_price,
                "entry_price": entry,
                "quantity": qty,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "stop_loss": sl,
                "take_profit": tp,
                "status": status,
                "trigger": trigger,
            }
        )

        if status == "triggered":
            alerts.append(
                {
                    "symbol": symbol,
                    "trigger": trigger,
                    "current_price": current_price,
                    "stop_loss": sl,
                    "take_profit": tp,
                    "pnl_pct": pnl_pct,
                }
            )

    return {"checked": checked, "alerts": alerts}


def _select_core_watchlist(config: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    defaults = CopilotDefaults()

    # 指数：优先用 opening_analysis.indices 配置
    indices_map = config.get("opening_analysis", {}).get("indices", {})
    index_codes = list(indices_map.values()) if isinstance(indices_map, dict) and indices_map else list(defaults.index_codes)
    # ETF：优先用 etf_trading.enabled_etfs
    etfs = config.get("etf_trading", {}).get("enabled_etfs", [])
    if isinstance(etfs, list) and etfs:
        etf_codes = [str(x) for x in etfs]
    else:
        etf_codes = list(defaults.etf_codes)
    return index_codes, etf_codes


def _load_state(openclaw_workspace_dir: Path) -> Dict[str, Any]:
    p = openclaw_workspace_dir / "memory" / "copilot_state.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_state(openclaw_workspace_dir: Path, state: Dict[str, Any]) -> None:
    p = openclaw_workspace_dir / "memory" / "copilot_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def tool_trading_copilot(
    focus_etfs: Optional[str] = None,
    focus_stocks: Optional[str] = None,
    mode: str = "normal",  # light | normal | deep
    run_signal: Optional[bool] = None,
    signal_etf: Optional[str] = None,
    throttle_minutes: int = 5,
    timezone: str = "Asia/Shanghai",
    disable_network_fetch: bool = False,
    output_format: str = "feishu_card",  # feishu_card | json
    include_snapshot: bool = False,
    send_feishu_card: bool = False,
    feishu_webhook_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：交易助手统一入口（最小可用版）。

    - 自动完成：交易状态 → A股时段细分 → 市场快扫 → (条件触发) 信号 → 持仓检查
    - 输出：结构化摘要（低上下文）
    """
    try:
        now = _now_shanghai(timezone)

        # OpenClaw workspace（用于 positions/state）
        home = Path.home()
        openclaw_workspace_dir = home / ".openclaw" / "workspaces" / "etf-options-ai-assistant"

        config = load_system_config()
        index_codes, etf_codes = _select_core_watchlist(config)

        if focus_etfs:
            etf_codes = [x.strip() for x in focus_etfs.split(",") if x.strip()]
        if focus_stocks:
            stock_codes = [x.strip() for x in focus_stocks.split(",") if x.strip()]
        else:
            stock_codes = []

        # 0) 交易粗状态 + A股细时段
        trading_status = tool_check_trading_status()
        a_share_regime = tool_get_a_share_market_regime(timezone=timezone)

        # 1) 快扫：指数 + ETF + A50 + 外围
        # 说明：在受限运行环境（例如 IDE 沙箱）中，外部行情域名可能不可访问；
        # 因此提供 disable_network_fetch 让上层在无法联网时快速降级，不阻塞整个回合。
        if disable_network_fetch:
            idx_rows = []
            etf_rows = []
            a50_res = {"success": False, "data": None, "message": "network_fetch_disabled"}
            global_res = {"success": False, "data": None, "message": "network_fetch_disabled"}
            sentiment_pack = {"score": 50, "factors": {}, "note": "network_fetch_disabled"}
        else:
            idx_res = tool_fetch_index_data(data_type="realtime", index_code=",".join(index_codes))
            idx_rows = _as_list(idx_res.get("data")) if idx_res.get("success") else []

            etf_rows: List[Dict[str, Any]] = []
            for code in etf_codes[:6]:  # 限制数量，避免过慢
                r = tool_fetch_etf_data(data_type="realtime", etf_code=code)
                if r.get("success") and r.get("data"):
                    d = r.get("data")
                    if isinstance(d, dict):
                        etf_rows.append(d)
                    elif isinstance(d, list) and d:
                        etf_rows.append(d[0])

            a50_res = tool_fetch_a50_data(data_type="realtime")
            global_res = tool_fetch_index_data(data_type="global_spot")
            a50_spot = a50_res.get("spot_data") if isinstance(a50_res, dict) else None
            a50_chg = _safe_float(a50_spot.get("change_pct")) if isinstance(a50_spot, dict) and a50_spot.get("change_pct") is not None else None
            etf_amt_avg_5d = None
            try:
                # 用核心 ETF（第一个）作为量能 proxy（可按需扩展为“核心池汇总”）
                if etf_codes:
                    etf_amt_avg_5d = _fetch_etf_amount_avg_5d(etf_codes[0])
            except Exception:
                etf_amt_avg_5d = None
            sentiment_pack = _compute_sentiment_score_v2(
                index_rows=idx_rows,
                etf_rows=etf_rows,
                a50_change_pct=a50_chg,
                etf_amount_avg_5d=etf_amt_avg_5d,
            )

        # 2) 是否跑信号（节流）
        state = _load_state(openclaw_workspace_dir)
        last_signal_ts = state.get("last_signal_ts")
        allow_signal = True
        if last_signal_ts:
            try:
                last = datetime.fromisoformat(str(last_signal_ts))
                delta_min = (now - last.astimezone(pytz.timezone(timezone))).total_seconds() / 60
                if delta_min < max(1, throttle_minutes):
                    allow_signal = False
            except Exception:
                pass

        should_run_signal = False
        if run_signal is True:
            should_run_signal = True
        elif run_signal is False:
            should_run_signal = False
        else:
            # 自动触发：极值情绪 or deep 模式
            should_run_signal = mode == "deep" or sentiment_pack.get("score", 50) >= 75 or sentiment_pack.get("score", 50) <= 25

        signal_data = None
        signal_note = None
        if should_run_signal and allow_signal and not disable_network_fetch:
            # 非连续交易时段降级：仍可生成“预案”，但标注不可立即执行
            primary = signal_etf or (etf_codes[0] if etf_codes else "510300")
            signal_data = tool_generate_signals(underlying=primary)
            state["last_signal_ts"] = now.isoformat()
            state["last_signal_etf"] = primary
            _save_state(openclaw_workspace_dir, state)
        elif should_run_signal and not allow_signal:
            signal_note = f"信号重流程已节流（{throttle_minutes} 分钟内不重复跑）"
        elif should_run_signal and disable_network_fetch:
            signal_note = "当前运行环境禁用联网抓取，信号重流程已跳过"

        # 3) 持仓检查（若有 positions.json）
        positions, positions_path = _load_positions(openclaw_workspace_dir)
        pos_check = _check_positions([p for p in positions if p.get("status", "open") == "open"]) if positions else {"checked": [], "alerts": []}

        sentiment_score = int(sentiment_pack.get("score", 50))

        # 4) 统一摘要输出（并提供飞书卡片 payload）
        ts = now.strftime("%Y-%m-%d %H:%M")
        trading_cn = (trading_status.get("data") or {}).get("market_status_cn") if isinstance(trading_status, dict) else None
        trading_cn = trading_cn or "未知"
        phase = (a_share_regime.get("data") or {}).get("phase") if isinstance(a_share_regime, dict) else None

        a50_spot = a50_res.get("spot_data") if isinstance(a50_res, dict) else None

        signal_brief = None
        if isinstance(signal_data, dict) and signal_data.get("data"):
            sd = signal_data.get("data") or {}
            if isinstance(sd, dict):
                st = sd.get("signal_type")
                ss = sd.get("signal_strength")
                if st:
                    signal_brief = f"{st} ({_safe_float(ss, 0.0):.2f})" if ss is not None else str(st)
        if signal_note and not signal_brief:
            signal_brief = signal_note

        feishu_card = _build_feishu_copilot_card(
            ts=ts,
            sentiment_score=sentiment_score,
            trading_status_cn=trading_cn,
            phase=phase,
            indices=idx_rows,
            etfs=etf_rows,
            a50_spot=a50_spot if isinstance(a50_spot, dict) else None,
            signal_brief=signal_brief,
            position_alerts=pos_check.get("alerts") or [],
        )

        summary: Dict[str, Any] = {
            "market_status": {
                "trading_status": trading_status.get("data"),
                "a_share_regime": a_share_regime.get("data"),
                "sentiment_score": sentiment_score,
                "sentiment_factors": sentiment_pack.get("factors"),
                "sentiment_note": sentiment_pack.get("note"),
            },
            "signal": {
                "ran": bool(signal_data),
                "note": signal_note,
                "result": signal_data.get("data") if isinstance(signal_data, dict) else None,
                "success": signal_data.get("success") if isinstance(signal_data, dict) else None,
                "message": signal_data.get("message") if isinstance(signal_data, dict) else None,
            },
            "positions": {
                "positions_path": positions_path,
                "checked": pos_check.get("checked"),
                "alerts": pos_check.get("alerts"),
            },
            "feishu_card": feishu_card,
        }

        send_result = None
        if send_feishu_card:
            if not FEISHU_CARD_SEND_AVAILABLE:
                send_result = {"success": False, "message": "feishu card sender not available"}
            else:
                send_result = tool_send_feishu_card_webhook(card=feishu_card, webhook_url=feishu_webhook_url)
            summary["feishu_send"] = send_result

        if include_snapshot:
            summary["snapshot"] = {
                "indices": idx_rows,
                "etfs": etf_rows,
                "a50": a50_res if isinstance(a50_res, dict) else None,
                "global": global_res.get("data") if isinstance(global_res, dict) else None,
            }

        return {
            "success": True,
            "message": "trading-copilot 完成",
            "data": summary if output_format != "feishu_card" else {"feishu_card": feishu_card, "summary": summary},
            "meta": {
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "mode": mode,
                "focus": {"etfs": etf_codes, "stocks": stock_codes},
            },
        }
    except Exception as e:
        return {"success": False, "message": f"trading-copilot 执行失败: {e}", "data": None}

