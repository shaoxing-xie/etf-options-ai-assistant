"""
进程内串接：宽基指数 / ETF 实时 + 组合风险快照 → 标准 report → 钉钉巡检快报。

供 Cron 单次 tool_call，避免 Gateway 多轮传递大 JSON 与 idle 超时。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    import pytz
except ImportError:  # pragma: no cover
    pytz = None  # type: ignore

_INDEX_CODES = "000300,399006,000905"
_ETF_CODES = "510300,510500,159915"


def _now_sh() -> datetime:
    if pytz is None:
        return datetime.now()
    return datetime.now(pytz.timezone("Asia/Shanghai"))


def _load_inspection_tail_cfg() -> Dict[str, Any]:
    try:
        from src.config_loader import load_system_config

        cfg = load_system_config(use_cache=True)
        seg = cfg.get("wide_inspection_tail_advice")
        return seg if isinstance(seg, dict) else {}
    except Exception:
        return {}


def _load_market_tail_cfg() -> Dict[str, Any]:
    try:
        from src.config_loader import load_system_config

        cfg = load_system_config(use_cache=True)
        seg = cfg.get("wide_inspection_overnight_refs")
        return seg if isinstance(seg, dict) else {}
    except Exception:
        return {}


def _parse_debug_now(debug_now: Optional[str]) -> Optional[datetime]:
    s = str(debug_now or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            if pytz is not None:
                return pytz.timezone("Asia/Shanghai").localize(dt)
            return dt
        except Exception:
            continue
    return None


def _rows_from_payload(data: Any) -> List[Dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _norm_code6(raw: Any) -> str:
    """统一 sh510300 / sz159915 / 510300 → 可比的 6 位数字符串（指数/ETF 列表键）。"""
    t = str(raw or "").strip().upper().replace(".SH", "").replace(".SZ", "")
    if t.startswith("SH") and len(t) > 2:
        t = t[2:]
    if t.startswith("SZ") and len(t) > 2:
        t = t[2:]
    # 纯数字保留（含前导零）
    if t.isdigit():
        return t
    return t


def _rows_to_map_by_code(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """按规范化 code 索引；同一行可同时用原始 code 与规范键命中。"""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        raw = str(r.get("code") or "").strip()
        if not raw:
            continue
        out[raw] = r
        k = _norm_code6(raw)
        if k and k != raw:
            out[k] = r
    return out


def _etf_pct_and_price(row: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    if row.get("found") is False:
        return None, None
    if "change_percent" in row and row.get("change_percent") is not None:
        try:
            pct = float(row["change_percent"])
            price = float(row.get("current_price") or row.get("latest_price") or 0)
            return pct, price if price > 0 else None
        except (TypeError, ValueError):
            pass
    lp = row.get("latest_price")
    pc = row.get("prev_close")
    try:
        lpf = float(lp) if lp is not None else 0.0
        pcf = float(pc) if pc is not None else 0.0
        if lpf > 0 and pcf > 0:
            pct = (lpf - pcf) / pcf * 100.0
            return pct, lpf
    except (TypeError, ValueError):
        pass
    return None, None


def _index_pct_and_price(row: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    try:
        pct = row.get("change_percent")
        if pct is None:
            ch = float(row.get("change") or 0)
            prev = float(row.get("prev_close") or 0)
            cur = float(row.get("current_price") or 0)
            if prev > 0 and cur > 0 and ch == 0:
                ch = cur - prev
            if prev > 0:
                pct = (ch / prev) * 100.0
            else:
                pct = None
        else:
            pct = float(pct)
        price = float(row.get("current_price") or 0)
        return (pct, price if price > 0 else None)
    except (TypeError, ValueError):
        return None, None


def _fmt_pct(pct: Optional[float]) -> str:
    if pct is None:
        return "数据不足"
    if abs(pct) > 15:
        return "数据不足"
    return f"{pct:.2f}%"


def _strength_label(pct: Optional[float]) -> str:
    if pct is None:
        return "数据不足"
    if pct > 0.25:
        return "偏强"
    if pct < -0.25:
        return "偏弱"
    return "中性"


def _style_judgment(hs: Optional[float], gem: Optional[float], zz: Optional[float]) -> str:
    if hs is None or zz is None:
        return "数据不足"
    diff = hs - zz
    if diff > 0.15:
        return "大盘蓝筹相对占优"
    if diff < -0.15:
        return "中小盘成长相对占优"
    return "风格均衡"


def _ashare_minutes(now: datetime) -> int:
    return now.hour * 60 + now.minute


def _session_segment(now: datetime) -> str:
    """交易日内的时段：盘前 / 连续竞价 / 午休 / 盘后（用于 remain_window 与 market_state，避免把凌晨盘前误判为收盘）。"""
    mn = _ashare_minutes(now)
    open_m = 9 * 60 + 30
    lunch_s = 11 * 60 + 30
    lunch_e = 13 * 60
    close_m = 15 * 60
    if mn < open_m:
        return "pre_open"
    if mn >= close_m:
        return "after_close"
    if lunch_s <= mn < lunch_e:
        return "lunch"
    return "open"


def _minutes_to_close_sh(now: datetime) -> Optional[int]:
    """A 股连续竞价剩余到 11:30 或 15:00 的近似分钟数；盘前/午休/盘后返回 None。"""
    h, m = now.hour, now.minute
    mins_now = h * 60 + m
    open_m = 9 * 60 + 30
    lunch_e = 11 * 60 + 30
    aft_s = 13 * 60
    close_m = 15 * 60
    if mins_now < open_m or mins_now >= close_m:
        return None
    if lunch_e <= mins_now < aft_s:
        # 午休：返回到下午开盘前
        return None
    if mins_now < lunch_e:
        end = lunch_e
    else:
        end = close_m
    return max(0, end - mins_now)


def _remain_window_text(now: datetime, trading: bool) -> str:
    if not trading:
        return "0"
    m = _minutes_to_close_sh(now)
    if m is not None:
        return str(int(m))
    seg = _session_segment(now)
    if seg == "pre_open":
        return "盘前"
    if seg == "lunch":
        return "午休"
    if seg == "after_close":
        return "收盘"
    return "数据不足"


def _next_update_hint(phase: str, trading: bool, now: datetime) -> str:
    if not trading:
        return "下一交易日"
    labels = {"morning": "早盘", "midday": "午间", "afternoon": "下午"}
    label = labels.get(phase, "盘中")
    seg = _session_segment(now)
    # 盘前：避免写「约30分钟后」与真实时钟严重不符
    if seg == "pre_open":
        return f"开盘后可关注当日{label}巡检推送"
    if seg == "lunch":
        return "下午开盘后"
    if seg == "after_close":
        return "下一交易日"
    return f"约30分钟后（{label}巡检）"


def _market_state_token(now: datetime, trading: bool) -> str:
    if not trading:
        return "非交易日"
    m = _minutes_to_close_sh(now)
    if m is not None:
        return "open"
    seg = _session_segment(now)
    if seg == "pre_open":
        return "pre_open"
    if seg == "lunch":
        return "lunch"
    if seg == "after_close":
        return "after_close"
    return "open"


def _build_non_trading_report(now: datetime) -> Dict[str, Any]:
    d = now.strftime("%Y-%m-%d")
    t = now.strftime("%H:%M")
    base = {k: "数据不足" for k in (
        "hs300_change", "hs300_strength", "gem_change", "gem_strength",
        "zz500_change", "zz500_strength", "style_judgment",
        "510300_price", "510300_change", "510300_position", "510300_resist", "510300_support",
        "510500_price", "510500_change", "510500_position", "510500_resist", "510500_support",
        "159915_price", "159915_change", "159915_position", "159915_resist", "159915_support",
        "focus1", "focus2", "focus3",
        "510300_action", "510500_action", "159915_action",
        "risk_level", "position_suggest",
        "var_snapshot", "max_dd_snapshot", "current_dd_snapshot", "position_risk_snapshot",
    )}
    base.update({
        "date": d,
        "time": t,
        "time_ref": "非交易日",
        "remain_window": "0",
        "market_state": "非交易日",
        "next_update": "下一交易日",
    })
    return base


def _try_enhance_510300_position(base_position: str) -> str:
    parts: List[str] = []
    if base_position and base_position != "数据不足":
        parts.append(base_position)
    try:
        from plugins.analysis.intraday_range import tool_predict_intraday_range

        r = tool_predict_intraday_range(symbol="510300")
        if r.get("success") and isinstance(r.get("data"), dict):
            d = r["data"]
            lo = d.get("lower_bound") or d.get("lower")
            up = d.get("upper_bound") or d.get("upper")
            if lo is not None and up is not None:
                parts.append(f"日内预测区间：{float(lo):.3f}~{float(up):.3f}")
    except Exception:
        pass
    try:
        from plugins.analysis.technical_indicators import tool_calculate_technical_indicators

        r2 = tool_calculate_technical_indicators(
            symbol="510300",
            data_type="etf_minute",
            timeframe_minutes=30,
            lookback_days=5,
        )
        if r2.get("success") and r2.get("message"):
            msg = str(r2.get("message") or "")
            compact = re.sub(r"\s+", " ", msg).strip()
            if len(compact) > 220:
                compact = compact[:220] + "…"
            if compact:
                parts.append(f"30m技术：{compact}")
    except Exception:
        pass
    if not parts:
        return "数据不足"
    return "；".join(parts)


def _focus_bullets(
    hs: Optional[float], gem: Optional[float], zz: Optional[float], trading: bool,
) -> Tuple[str, str, str]:
    if not trading:
        return ("数据不足", "数据不足", "数据不足")
    if hs is None and gem is None and zz is None:
        return ("数据不足", "数据不足", "数据不足")
    f1 = "指数分化有限，关注量能持续性" if hs is not None else "数据不足"
    if gem is not None and zz is not None:
        f2 = "创业板指与中证500相对强弱决定成长风格持续性"
    else:
        f2 = "数据不足"
    f3 = "严控单标的回撤，遵守组合风控阈值"
    return (f1, f2, f3)


def _action_line(pct: Optional[float]) -> str:
    if pct is None:
        return "数据不足"
    if pct > 0.4:
        return "持有观望"
    if pct < -0.4:
        return "减仓观望"
    return "持有观望"


def _tail_view_opinion(pct: Optional[float], up_th: float = 0.35, dn_th: float = -0.35) -> Tuple[str, str]:
    if pct is None:
        return "持有", "数据不足，维持中性。"
    if pct >= up_th:
        return "持有", "趋势偏强，方向层面维持持有。"
    if pct <= dn_th:
        return "减仓", "趋势偏弱，方向层面建议减仓。"
    return "持有", "趋势中性，维持持有观察。"


def _build_tail_advice(report: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    def _p(k: str) -> Optional[float]:
        try:
            raw = str(report.get(k) or "")
            m = re.search(r"(-?\d+(?:\.\d+)?)", raw)
            return float(m.group(1)) if m else None
        except Exception:
            return None

    hs = _p("hs300_change")
    gem = _p("gem_change")
    zz = _p("zz500_change")
    var_pct = _p("var_snapshot")
    cur_dd = _p("current_dd_snapshot")
    trend_base = None
    valid = [x for x in (hs, gem, zz) if x is not None]
    if valid:
        trend_base = sum(valid) / len(valid)

    trend_cfg = cfg.get("trend") if isinstance(cfg.get("trend"), dict) else {}
    timing_cfg = cfg.get("timing") if isinstance(cfg.get("timing"), dict) else {}
    risk_cfg = cfg.get("risk") if isinstance(cfg.get("risk"), dict) else {}
    paths_cfg = cfg.get("paths") if isinstance(cfg.get("paths"), dict) else {}

    trend_up = float(trend_cfg.get("up_threshold_pct", 0.30))
    trend_dn = float(trend_cfg.get("down_threshold_pct", -0.30))
    trend_action, trend_reason = _tail_view_opinion(trend_base, up_th=trend_up, dn_th=trend_dn)
    # 盘中涨幅过热近似替代：任一核心指数 > 1.5% 判作节奏偏热
    timing_hot_th = float(timing_cfg.get("hot_change_pct", 1.5))
    timing_hot = any((x is not None and x >= timing_hot_th) for x in (hs, gem, zz))
    timing_gate_hit = False
    if timing_hot:
        timing_action, timing_reason = "减仓", "短线涨幅偏快，节奏层建议降速。"
        timing_gate_hit = True
    else:
        timing_action, timing_reason = "持有", "未见明显过热，节奏层维持持有。"

    risk_action, risk_reason = "持有", "风控指标在常规区间。"
    risk_gate_hit = "none"
    dd_exit = float(risk_cfg.get("drawdown_exit_pct_lte", -10.0))
    dd_warn = float(risk_cfg.get("drawdown_warn_pct_lte", -5.0))
    var_exit = float(risk_cfg.get("var_exit_pct_gte", 2.5))
    var_warn = float(risk_cfg.get("var_warn_pct_gte", 2.0))
    if (cur_dd is not None and cur_dd <= dd_exit) or (var_pct is not None and var_pct >= var_exit):
        risk_action, risk_reason = "退出", "回撤/VaR 触发危险阈值。"
        risk_gate_hit = "hard_risk_gate"
    elif (cur_dd is not None and cur_dd <= dd_warn) or (var_pct is not None and var_pct >= var_warn):
        risk_action, risk_reason = "减仓", "回撤/VaR 进入警戒区间。"
        risk_gate_hit = "warn_risk_gate"

    # 路径映射（门禁优先）
    conservative = {"action": "持有", "cap": str(paths_cfg.get("conservative_cap", "20%"))}
    neutral = {"action": "持有", "cap": str(paths_cfg.get("neutral_cap", "40%"))}
    aggressive = {"action": "持有", "cap": str(paths_cfg.get("aggressive_cap", "60%"))}
    if risk_action == "退出":
        conservative, neutral, aggressive = (
            {"action": "退出", "cap": "0%"},
            {"action": "减仓", "cap": "10%"},
            {"action": "减仓", "cap": "20%"},
        )
    elif risk_action == "减仓" or (trend_action == "减仓" and timing_action == "减仓"):
        conservative, neutral, aggressive = (
            {"action": "减仓", "cap": "10%"},
            {"action": "减仓", "cap": "20%"},
            {"action": "持有", "cap": "40%"},
        )
    elif timing_action == "减仓":
        conservative, neutral, aggressive = (
            {"action": "持有", "cap": "20%"},
            {"action": "持有", "cap": "40%"},
            {"action": "持有", "cap": "60%"},
        )

    focus_cfg = cfg.get("next_focus") if isinstance(cfg.get("next_focus"), list) else []
    defaults = ["A50期货夜盘方向", "晚间重大政策/事件", "隔夜美股与中概指数波动"]
    next_focus = [str(focus_cfg[i]) if i < len(focus_cfg) else defaults[i] for i in range(3)]

    indicator_conclusion = "趋势与风控未冲突，按中性路径管理仓位。"
    if risk_action == "退出":
        indicator_conclusion = "风控门禁已触发，优先退出或显著降仓，不做激进动作。"
    elif risk_action == "减仓" or timing_action == "减仓":
        indicator_conclusion = "短线偏热或风险抬升，当前以持有/减仓为主，不建议追高。"

    return {
        "next_day_basis": "结合当日结构、风险快照与隔夜变量可用性进行次日预判。",
        "trend": {"action": trend_action, "reason": trend_reason, "basis": f"核心指数均值变动 {trend_base:.2f}%" if trend_base is not None else "指数数据不足"},
        "timing": {"action": timing_action, "reason": timing_reason, "basis": f"过热阈值 {timing_hot_th:.2f}%，当前命中={timing_gate_hit}"},
        "risk": {"action": risk_action, "reason": risk_reason, "basis": f"VaR阈值 {var_warn:.2f}/{var_exit:.2f}%，回撤阈值 {dd_warn:.2f}/{dd_exit:.2f}%", "gate_hit": risk_gate_hit},
        "paths": {
            "conservative": conservative,
            "neutral": neutral,
            "aggressive": aggressive,
            "default_path": "中性",
        },
        "indicator_conclusion": indicator_conclusion,
        "gate_hits": [x for x in ["timing_overheat_gate" if timing_gate_hit else None, risk_gate_hit if risk_gate_hit != "none" else None] if x],
        "next_focus": next_focus,
    }


def _resist_support_from_range(
    price: Optional[float], high: Optional[float], low: Optional[float],
) -> Tuple[str, str]:
    if price is None or price <= 0:
        return ("数据不足", "数据不足")
    h = high if high and high > price else None
    l = low if low and low < price else None
    if h is not None and l is not None:
        return (f"{h:.3f}", f"{l:.3f}")
    return ("数据不足", "数据不足")


def build_inspection_report(
    phase: str = "midday",
    *,
    fetch_mode: str = "production",
    debug_force_tail_section: bool = False,
    debug_now: Optional[str] = None,
) -> Dict[str, Any]:
    """
    采集并组装 tool_send_signal_risk_inspection 所需的 report 扁平字典。
    """
    from plugins.utils.trading_day import is_trading_day

    now = _parse_debug_now(debug_now) if fetch_mode == "test" else None
    if now is None:
        now = _now_sh()
    phase = (phase or "midday").strip().lower()
    if phase not in ("morning", "midday", "afternoon"):
        phase = "midday"

    tail_cfg = _load_inspection_tail_cfg()
    market_tail_cfg = _load_market_tail_cfg()
    trading = bool(is_trading_day(now))
    if not trading and not (fetch_mode == "test" and debug_force_tail_section):
        return _build_non_trading_report(now)

    from plugins.merged.fetch_index_data import tool_fetch_index_data
    from plugins.merged.fetch_etf_data import tool_fetch_etf_data
    from plugins.risk.portfolio_risk_snapshot import tool_portfolio_risk_snapshot

    idx_resp = tool_fetch_index_data(
        data_type="realtime",
        index_code=_INDEX_CODES,
        mode=fetch_mode,
    )
    etf_resp = tool_fetch_etf_data(
        data_type="realtime",
        etf_code=_ETF_CODES,
        mode=fetch_mode,
    )
    pr = tool_portfolio_risk_snapshot(lookback_days=120)

    idx_rows = _rows_from_payload(idx_resp.get("data") if isinstance(idx_resp, dict) else None)
    etf_rows = _rows_from_payload(etf_resp.get("data") if isinstance(etf_resp, dict) else None)
    by_idx = _rows_to_map_by_code(idx_rows)
    by_etf = _rows_to_map_by_code(etf_rows)

    def idx_pct(code: str) -> Tuple[Optional[float], Optional[float]]:
        row = by_idx.get(code)
        if not row:
            return None, None
        return _index_pct_and_price(row)

    hs_pct, _ = idx_pct("000300")
    gem_pct, _ = idx_pct("399006")
    zz_pct, _ = idx_pct("000905")

    report: Dict[str, Any] = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "time_ref": now.strftime("%H:%M"),
        "hs300_change": _fmt_pct(hs_pct),
        "hs300_strength": _strength_label(hs_pct),
        "gem_change": _fmt_pct(gem_pct),
        "gem_strength": _strength_label(gem_pct),
        "zz500_change": _fmt_pct(zz_pct),
        "zz500_strength": _strength_label(zz_pct),
        "style_judgment": _style_judgment(hs_pct, gem_pct, zz_pct),
        "remain_window": _remain_window_text(now, True),
        "market_state": _market_state_token(now, True),
        "next_update": _next_update_hint(phase, True, now),
    }

    f1, f2, f3 = _focus_bullets(hs_pct, gem_pct, zz_pct, True)
    report["focus1"], report["focus2"], report["focus3"] = f1, f2, f3

    etf_specs = (
        ("510300", "510300_price", "510300_change", "510300_position", "510300_resist", "510300_support", "510300_action"),
        ("510500", "510500_price", "510500_change", "510500_position", "510500_resist", "510500_support", "510500_action"),
        ("159915", "159915_price", "159915_change", "159915_position", "159915_resist", "159915_support", "159915_action"),
    )
    for code, pk, ck, posk, rk, sk, ak in etf_specs:
        row = by_etf.get(code, {})
        pct, price = _etf_pct_and_price(row)
        report[pk] = f"{price:.3f}" if price is not None else "数据不足"
        report[ck] = _fmt_pct(pct)
        high = row.get("high")
        low = row.get("low")
        try:
            hf = float(high) if high is not None else None
            lf = float(low) if low is not None else None
        except (TypeError, ValueError):
            hf, lf = None, None
        rs, ss = _resist_support_from_range(price, hf, lf)
        report[rk], report[sk] = rs, ss
        if code == "510300":
            base_pos = "数据不足"
            if pct is not None and price is not None:
                dir_cn = "上涨" if pct >= 0 else "下跌"
                base_pos = f"现价{price:.3f}，日内{dir_cn}{_fmt_pct(pct)}"
            report[posk] = _try_enhance_510300_position(base_pos if base_pos else "数据不足")
        else:
            if pct is not None and price is not None:
                report[posk] = f"现价{price:.3f}，涨跌{_fmt_pct(pct)}"
            else:
                report[posk] = "数据不足"
        report[ak] = _action_line(pct)

    if pr.get("success") and isinstance(pr.get("data"), dict):
        pdata = pr["data"]
        report["portfolio_risk_snapshot"] = pdata
        report["var_snapshot"] = f"{float(pdata.get('var_historical_pct', 0)):.2f}%"
        report["max_dd_snapshot"] = f"{float(pdata.get('max_drawdown_pct', 0)):.2f}%"
        report["current_dd_snapshot"] = f"{float(pdata.get('current_drawdown_pct', 0)):.2f}%"
        pos = pdata.get("current_position_pct")
        flag = str(pdata.get("position_risk_flag") or "")
        if isinstance(pos, (int, float)):
            report["position_risk_snapshot"] = f"{float(pos):.0f}% / {flag or '数据不足'}"
        else:
            report["position_risk_snapshot"] = "数据不足"
        dd_f = str(pdata.get("drawdown_risk_flag") or "")
        if "alert" in dd_f or "alert" in flag:
            report["risk_level"] = "高"
        elif "warn" in dd_f or "warn" in flag:
            report["risk_level"] = "中"
        else:
            report["risk_level"] = "中"
        pos_pct = float(pdata.get("current_position_pct") or 0)
        if pos_pct >= 85:
            report["position_suggest"] = "控仓/预留缓冲"
        elif pos_pct <= 30:
            report["position_suggest"] = "可按计划逐步加仓"
        else:
            report["position_suggest"] = "维持计划仓位"
    else:
        for k in ("var_snapshot", "max_dd_snapshot", "current_dd_snapshot", "position_risk_snapshot"):
            report[k] = "数据不足"
        report["risk_level"] = "数据不足"
        report["position_suggest"] = "数据不足"

    gate = str(tail_cfg.get("time_gate_after") or "14:00")
    mm = re.search(r"^(\d{1,2}):(\d{2})$", gate)
    gate_min = (int(mm.group(1)) * 60 + int(mm.group(2))) if mm else (14 * 60)
    minutes = _ashare_minutes(now)
    tail_enabled = bool(tail_cfg.get("enabled", True)) and (
        bool(trading and minutes > gate_min) or bool(fetch_mode == "test" and debug_force_tail_section)
    )
    report["tail_section_enabled"] = tail_enabled
    if tail_enabled:
        report["tail_advice"] = _build_tail_advice(report, tail_cfg)
        refs = market_tail_cfg.get("sources") if isinstance(market_tail_cfg.get("sources"), dict) else {}
        ref_items = []
        unavailable = []
        for key, label in (("a50_futures", "A50夜盘"), ("usd_cny", "汇率"), ("us_equity_futures", "美股期货")):
            info = refs.get(key) if isinstance(refs.get(key), dict) else {}
            enabled = bool(info.get("enabled", False))
            status = "available" if enabled else "unavailable"
            ref_items.append({"name": label, "status": status})
            if not enabled:
                unavailable.append(label)
        report["tail_advice"]["overnight_refs"] = ref_items
        if unavailable:
            report["tail_advice"]["degrade_reason"] = f"隔夜变量部分缺失（{','.join(unavailable)}），已降级为保守解释口径。"
        report["tail_time_gate"] = "post_14_00" if (trading and minutes > gate_min) else "debug_forced"
    return report


def tool_run_signal_risk_inspection_and_send(
    phase: str = "midday",
    mode: str = "prod",
    fetch_mode: str = "production",
    debug_force_tail_section: bool = False,
    debug_now: Optional[str] = None,
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
) -> Dict[str, Any]:
    """
    进程内拉取宽基行情与组合风险快照，组装 report 并调用 tool_send_signal_risk_inspection 发钉钉。

    Args:
        phase: morning | midday | afternoon（与三档 Cron 对应）。
        mode: prod | test，钉钉发送模式。
        fetch_mode: production | test，透传指数/ETF 实时采集（test 跳过交易日门禁）。
    """
    from plugins.notification.send_signal_risk_inspection import tool_send_signal_risk_inspection

    if str(mode).lower() != "test":
        debug_force_tail_section = False
        debug_now = None
    report = build_inspection_report(
        phase=phase,
        fetch_mode=fetch_mode,
        debug_force_tail_section=debug_force_tail_section,
        debug_now=debug_now,
    )
    out = tool_send_signal_risk_inspection(
        report=report,
        phase=phase,
        mode=mode,
        webhook_url=webhook_url,
        secret=secret,
        keyword=keyword,
    )
    if isinstance(out, dict):
        out.setdefault("data", {})
        if isinstance(out["data"], dict):
            out["data"]["runner_phase"] = phase
            out["data"]["fetch_mode"] = fetch_mode
    return out
