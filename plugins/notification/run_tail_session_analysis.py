"""
进程内串接：14:40 日经225ETF（513880）尾盘监控与多角度建议。

目标：
- 生成 report_type=tail_session 的结构化 report_data
- 不输出唯一交易结论，仅输出分层建议 + 可选路径（用户最终决策）
"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

try:
    import pytz
except ImportError:  # pragma: no cover
    pytz = None  # type: ignore


logger = logging.getLogger(__name__)


def _now_sh() -> datetime:
    if pytz is None:
        return datetime.now()
    return datetime.now(pytz.timezone("Asia/Shanghai"))


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _safe_step(
    name: str,
    fn: Any,
    errors: List[Dict[str, str]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        errors.append({"step": name, "error": str(e)})
        logger.warning("tail_runner step %s failed: %s", name, e, exc_info=True)
        return None


def _load_tail_cfg() -> Dict[str, Any]:
    try:
        from src.config_loader import load_system_config

        cfg = load_system_config(use_cache=True)
        seg = cfg.get("nikkei_tail_session")
        return seg if isinstance(seg, dict) else {}
    except Exception as e:
        logger.warning("tail_runner load config failed: %s", e)
        return {}


def _load_market_data_cfg() -> Dict[str, Any]:
    try:
        path = Path(__file__).resolve().parents[2] / "config" / "domains" / "market_data.yaml"
        with path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception as e:
        logger.warning("tail_runner load market_data config failed: %s", e)
        return {}


def _resolve_manual_iopv(
    market_cfg: Dict[str, Any],
    etf_code: str,
    trade_date: str,
) -> Optional[Dict[str, Any]]:
    root = market_cfg.get("iopv_fallback") if isinstance(market_cfg.get("iopv_fallback"), dict) else {}
    overrides = root.get("manual_iopv_overrides") if isinstance(root.get("manual_iopv_overrides"), dict) else {}
    seg = overrides.get(str(etf_code))
    if not isinstance(seg, dict):
        return None
    updated_date = str(seg.get("updated_date") or "").strip()
    if not updated_date or updated_date != trade_date:
        return None
    iopv = _safe_float(seg.get("iopv"))
    if iopv is None or iopv <= 0:
        return None
    return {
        "iopv": iopv,
        "updated_date": updated_date,
        "source": str(seg.get("source") or "manual_config"),
    }


def _estimate_iopv(
    market_cfg: Dict[str, Any],
    etf_code: str,
    index_day_ret_pct: Optional[float],
    latest_price: Optional[float],
) -> Optional[Dict[str, Any]]:
    root = market_cfg.get("iopv_fallback") if isinstance(market_cfg.get("iopv_fallback"), dict) else {}
    est_cfg = root.get("estimation") if isinstance(root.get("estimation"), dict) else {}
    if not bool(est_cfg.get("enabled", False)):
        return None
    nav_map = est_cfg.get("etf_nav_baseline") if isinstance(est_cfg.get("etf_nav_baseline"), dict) else {}
    nav_seg = nav_map.get(str(etf_code)) if isinstance(nav_map.get(str(etf_code)), dict) else {}
    nav = _safe_float(nav_seg.get("nav"))
    if nav is None or nav <= 0 or index_day_ret_pct is None:
        return None
    iopv_est = nav * (1.0 + index_day_ret_pct / 100.0)
    if iopv_est <= 0:
        return None
    premium_est = None
    if latest_price is not None and latest_price > 0:
        premium_est = (latest_price - iopv_est) / iopv_est * 100.0
    conf_seg = est_cfg.get("confidence") if isinstance(est_cfg.get("confidence"), dict) else {}
    conf = _safe_float(conf_seg.get("with_nav_and_index"))
    if conf is None:
        conf = 0.55
    return {
        "iopv_est": iopv_est,
        "premium_est": premium_est,
        "est_confidence": conf,
        "basis": {
            "nav": nav,
            "nav_date": str(nav_seg.get("nav_date") or ""),
            "index_day_ret_pct": index_day_ret_pct,
        },
    }


def _calc_rsi14(closes: List[float]) -> Optional[float]:
    if len(closes) < 15:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(x, 0.0) for x in deltas[-14:]]
    losses = [abs(min(x, 0.0)) for x in deltas[-14:]]
    avg_gain = sum(gains) / 14.0
    avg_loss = sum(losses) / 14.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _calc_streak_and_return(closes: List[float]) -> Tuple[int, float, Optional[float]]:
    if len(closes) < 2:
        return 0, 0.0, None
    streak = 0
    for i in range(len(closes) - 1, 0, -1):
        d = closes[i] - closes[i - 1]
        if d > 0:
            streak = streak + 1 if streak >= 0 else 1
        elif d < 0:
            streak = streak - 1 if streak <= 0 else -1
        else:
            break
    base = closes[-2] if len(closes) >= 2 else 0.0
    day_ret = ((closes[-1] - base) / base * 100.0) if base else 0.0
    streak_ret: Optional[float] = None
    if streak != 0:
        start_idx = len(closes) - 1 - abs(streak)
        if 0 <= start_idx < len(closes) and closes[start_idx] != 0:
            streak_ret = (closes[-1] - closes[start_idx]) / closes[start_idx] * 100.0
    return streak, day_ret, streak_ret


def _layer_cycle(ma25_dev: Optional[float], rsi14: Optional[float], close: Optional[float], ma25: Optional[float]) -> Dict[str, Any]:
    regime = "震荡"
    if close is not None and ma25 is not None:
        if close > ma25 and (rsi14 is None or rsi14 < 70):
            regime = "上升"
        elif close < ma25 and (rsi14 is not None and rsi14 <= 45):
            regime = "下行"
    return {
        "layer": "cycle",
        "regime": regime,
        "signals": {"ma25_dev_pct": ma25_dev, "rsi14": rsi14},
        "options": ["hold", "buy_light"] if regime == "上升" else (["hold", "reduce"] if regime == "下行" else ["hold"]),
    }


def _layer_timing(streak: int, premium_pct: Optional[float], rsi14: Optional[float], ma25_dev: Optional[float], cfg: Dict[str, Any]) -> Dict[str, Any]:
    tech_cfg = cfg.get("technical_thresholds") if isinstance(cfg.get("technical_thresholds"), dict) else {}
    st_cfg = cfg.get("streak_thresholds") if isinstance(cfg.get("streak_thresholds"), dict) else {}
    up_days = int(st_cfg.get("up_days", 5))
    down_days = int(st_cfg.get("down_days", 3))
    overbought = float(tech_cfg.get("rsi_overbought", 70))
    ma_over = float(tech_cfg.get("ma25_dev_overheat", 5.0))

    options: List[str] = ["hold"]
    reasons: List[str] = []
    if premium_pct is not None and premium_pct < 0 and streak <= -down_days:
        options = ["buy_light", "hold"]
        reasons.append("连跌+折价")
    if streak >= up_days or ((rsi14 is not None and rsi14 >= overbought) or (ma25_dev is not None and ma25_dev >= ma_over)):
        options = ["reduce", "hold"]
        reasons.append("过热/连续上涨")
    return {
        "layer": "timing",
        "signals": {"streak": streak, "premium_pct": premium_pct, "rsi_overbought": overbought, "ma25_dev_overheat": ma_over},
        "options": options,
        "reasons": reasons,
    }


def _layer_risk(premium_pct: Optional[float], liquidity_amount: Optional[float], manager_notice: bool, cfg: Dict[str, Any]) -> Dict[str, Any]:
    g = cfg.get("gate_rules") if isinstance(cfg.get("gate_rules"), dict) else {}
    p5 = float(((g.get("premium_hard_stop") or {}).get("trigger") or {}).get("premium_pct_gte", 5.0))
    p10 = float(((g.get("premium_extreme_exit_bias") or {}).get("trigger") or {}).get("premium_pct_gte", 10.0))
    liq_cfg = g.get("liquidity_guard_gate") if isinstance(g.get("liquidity_guard_gate"), dict) else {}
    min_amt = float((((liq_cfg.get("trigger") or {}).get("min_amount_yuan_lte")) or 2e7))

    gate_hits: List[str] = []
    options = ["hold", "reduce", "exit_wait"]
    if premium_pct is not None and premium_pct >= p10:
        gate_hits.append("premium_extreme")
    elif premium_pct is not None and premium_pct >= p5:
        gate_hits.append("premium_hard_stop")
    if manager_notice and premium_pct is not None and premium_pct >= 3.0:
        gate_hits.append("fund_manager_notice")
    if liquidity_amount is not None and liquidity_amount <= min_amt:
        gate_hits.append("poor_liquidity")
    if not gate_hits:
        options = ["hold", "buy_light", "reduce"]
    return {"layer": "risk", "gate_hits": gate_hits, "options": options}


def _resolve_decision_options(layer_cycle: Dict[str, Any], layer_timing: Dict[str, Any], layer_risk: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    profiles = cfg.get("option_profiles") if isinstance(cfg.get("option_profiles"), dict) else {}
    conservative = profiles.get("conservative") if isinstance(profiles.get("conservative"), dict) else {}
    neutral = profiles.get("neutral") if isinstance(profiles.get("neutral"), dict) else {}
    aggressive = profiles.get("aggressive") if isinstance(profiles.get("aggressive"), dict) else {}

    risk_options = set(layer_risk.get("options") or [])

    def _pick(profile: Dict[str, Any], fallback: str) -> str:
        arr = profile.get("preferred_actions") if isinstance(profile.get("preferred_actions"), list) else []
        for x in arr:
            if x in risk_options:
                return str(x)
        return fallback

    return {
        "conservative": {"action": _pick(conservative, "hold"), "max_position_pct": conservative.get("max_position_pct", 20)},
        "neutral": {"action": _pick(neutral, "hold"), "max_position_pct": neutral.get("max_position_pct", 40)},
        "aggressive": {"action": _pick(aggressive, "hold"), "max_position_pct": aggressive.get("max_position_pct", 60)},
        "layer_conflicts": {
            "cycle_options": layer_cycle.get("options"),
            "timing_options": layer_timing.get("options"),
            "risk_options": layer_risk.get("options"),
        },
    }


def _build_risk_notices(payload: Dict[str, Any], cfg: Dict[str, Any]) -> List[str]:
    rules = cfg.get("risk_notice_rules") if isinstance(cfg.get("risk_notice_rules"), dict) else {}
    notices: List[str] = []
    premium = _safe_float(payload.get("premium_pct"))
    rsi14 = _safe_float(payload.get("rsi14"))
    ma25_dev = _safe_float(payload.get("ma25_dev_pct"))
    manager_notice = bool(payload.get("manager_premium_notice"))
    data_quality = str(payload.get("data_quality") or "fresh")

    for _, block in rules.items():
        if not isinstance(block, dict):
            continue
        when = block.get("when") if isinstance(block.get("when"), dict) else {}
        msg = str(block.get("message") or "").strip()
        if not msg:
            continue
        ok = False
        if "premium_pct_gte" in when and premium is not None and premium >= float(when["premium_pct_gte"]):
            ok = True
        if "premium_pct_lt" in when and premium is not None and premium < float(when["premium_pct_lt"]):
            ok = True
        if "rsi14_gte" in when and rsi14 is not None and rsi14 >= float(when["rsi14_gte"]):
            ok = True
        if "ma25_dev_pct_gte" in when and ma25_dev is not None and ma25_dev >= float(when["ma25_dev_pct_gte"]):
            ok = True
        if "manager_premium_notice" in when and manager_notice == bool(when["manager_premium_notice"]):
            ok = True
        if "data_quality_in" in when and data_quality in [str(x) for x in (when.get("data_quality_in") or [])]:
            ok = True
        if ok:
            notices.append(msg)
    dedup: List[str] = []
    seen = set()
    for x in notices:
        if x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup


def build_tail_session_report_data(fetch_mode: str = "production") -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    errors: List[Dict[str, str]] = []
    cfg = _load_tail_cfg()
    market_cfg = _load_market_data_cfg()
    mode = fetch_mode if fetch_mode in ("production", "test") else "production"
    etf_code = str(cfg.get("etf_code") or "513880")
    index_symbol = str(cfg.get("index_symbol") or "^N225")

    from plugins.data_collection.utils.check_trading_status import tool_check_trading_status
    from plugins.merged.fetch_etf_data import tool_fetch_etf_data
    from plugins.data_collection.etf.fetch_realtime import tool_fetch_etf_iopv_snapshot
    from plugins.merged.fetch_index_data import tool_fetch_index_data
    from plugins.data_collection.index.fetch_global_hist_sina import tool_fetch_global_index_hist_sina
    from plugins.notification.run_opening_analysis import _safe_step as open_safe_step  # 保持统一错误记录形式

    safe = open_safe_step if callable(open_safe_step) else _safe_step

    rd: Dict[str, Any] = {
        "report_type": "tail_session",
        "runner_version": "tail_session_analysis_v1",
    }
    now = _now_sh()
    rd["date"] = now.strftime("%Y-%m-%d")
    rd["trade_date"] = rd["date"]
    rd["generated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")

    ts = safe("check_trading_status", tool_check_trading_status, errors)
    if ts is not None:
        rd["trading_status"] = ts

    iopv = safe("fetch_etf_iopv_snapshot", tool_fetch_etf_iopv_snapshot, errors, etf_code=etf_code)
    if iopv is not None:
        rd["tool_fetch_etf_iopv_snapshot"] = iopv

    etf_rt = safe(
        "fetch_etf_realtime",
        tool_fetch_etf_data,
        errors,
        data_type="realtime",
        etf_code=etf_code,
        mode=mode,
    )
    if etf_rt is not None:
        rd["tool_fetch_etf_realtime"] = etf_rt

    n225_hist = safe("fetch_n225_hist", tool_fetch_global_index_hist_sina, errors, symbol=index_symbol, limit=90)
    if n225_hist is not None:
        rd["tool_fetch_n225_hist"] = n225_hist

    overnight = safe(
        "fetch_global_spot_for_overnight",
        tool_fetch_index_data,
        errors,
        data_type="global_spot",
        mode=mode,
        index_codes="^IXIC,^DJI,^N225",
    )
    if overnight is not None:
        rd["tool_fetch_global_index_spot"] = overnight

    iopv_row = (iopv or {}).get("data") if isinstance(iopv, dict) else {}
    if isinstance(iopv_row, list):
        iopv_row = iopv_row[0] if iopv_row else {}
    rt_row = (etf_rt or {}).get("data") if isinstance(etf_rt, dict) else {}
    if isinstance(rt_row, list):
        rt_row = rt_row[0] if rt_row else {}

    latest_price = _safe_float((rt_row or {}).get("current_price")) or _safe_float((iopv_row or {}).get("latest_price"))
    premium_pct = _safe_float((iopv_row or {}).get("discount_pct"))
    if premium_pct is not None:
        premium_pct = -premium_pct
    iopv_val = _safe_float((iopv_row or {}).get("iopv"))
    amount = _safe_float((rt_row or {}).get("amount"))

    hist_rows = []
    if isinstance(n225_hist, dict):
        data = n225_hist.get("data")
        if isinstance(data, list):
            hist_rows = [x for x in data if isinstance(x, dict)]
    closes: List[float] = []
    for r in hist_rows:
        c = _safe_float(r.get("close"))
        if c is not None:
            closes.append(c)
    ma25 = sum(closes[-25:]) / 25.0 if len(closes) >= 25 else None
    close = closes[-1] if closes else None
    ma25_dev = ((close - ma25) / ma25 * 100.0) if (close is not None and ma25 not in (None, 0.0)) else None
    rsi14 = _calc_rsi14(closes)
    streak, day_ret, streak_ret = _calc_streak_and_return(closes)

    iopv_source = "realtime" if (iopv_val is not None and premium_pct is not None) else "unavailable"
    manual_iopv = _resolve_manual_iopv(market_cfg, etf_code=etf_code, trade_date=rd["trade_date"])
    iopv_est_pack = _estimate_iopv(market_cfg, etf_code=etf_code, index_day_ret_pct=day_ret, latest_price=latest_price)
    if iopv_source != "realtime" and manual_iopv is not None:
        iopv_val = _safe_float(manual_iopv.get("iopv"))
        premium_pct = ((latest_price - iopv_val) / iopv_val * 100.0) if (latest_price and iopv_val) else None
        iopv_source = "manual"
    elif iopv_source != "realtime" and iopv_est_pack is not None:
        iopv_val = _safe_float(iopv_est_pack.get("iopv_est"))
        premium_pct = _safe_float(iopv_est_pack.get("premium_est"))
        iopv_source = "estimated"

    manager_notice = bool((cfg.get("risk_notice_state") or {}).get("manager_premium_notice", False))
    layer_cycle = _layer_cycle(ma25_dev, rsi14, close, ma25)
    layer_timing = _layer_timing(streak, premium_pct, rsi14, ma25_dev, cfg)
    layer_risk = _layer_risk(premium_pct, amount, manager_notice, cfg)
    if iopv_source in ("estimated", "unavailable"):
        gate_hits = list(layer_risk.get("gate_hits") or [])
        gate_tag = "iopv_estimated_only" if iopv_source == "estimated" else "iopv_unavailable"
        if gate_tag not in gate_hits:
            gate_hits.append(gate_tag)
        layer_risk["gate_hits"] = gate_hits
        layer_risk["options"] = ["hold", "reduce", "exit_wait"]
    decision_options = _resolve_decision_options(layer_cycle, layer_timing, layer_risk, cfg)

    if iopv_source == "realtime":
        data_quality = "fresh"
    elif iopv_source == "manual":
        data_quality = "manual_override"
    elif iopv_source == "estimated":
        data_quality = "estimated"
    else:
        data_quality = "partial"
    risk_notices = _build_risk_notices(
        {
            "premium_pct": premium_pct,
            "rsi14": rsi14,
            "ma25_dev_pct": ma25_dev,
            "manager_premium_notice": manager_notice,
            "data_quality": data_quality,
        },
        cfg,
    )
    if iopv_source == "estimated":
        risk_notices.insert(0, "IOPV/溢价率当前为估算值，仅可作风险参考，建议保守执行。")
    if iopv_source == "unavailable":
        risk_notices.insert(0, "IOPV/溢价率当前不可用，已自动进入保守门禁（仅允许持有/减仓/观望）。")
    tech_cfg = cfg.get("technical_thresholds") if isinstance(cfg.get("technical_thresholds"), dict) else {}
    ma_over = float(tech_cfg.get("ma25_dev_overheat", 5.0))
    rsi_over = float(tech_cfg.get("rsi_overbought", 70))
    if ma25_dev is not None and ma25_dev >= ma_over:
        risk_notices.insert(0, f"MA25偏离 {ma25_dev:.2f}% 已超过 {ma_over:.2f}% 警戒线，触发短线过热预警。")
    if rsi14 is not None and rsi14 >= rsi_over:
        risk_notices.insert(0, f"RSI14={rsi14:.2f} 已达到/超过 {rsi_over:.0f}，触发超买预警。")

    rd["tail_session_snapshot"] = {
        "etf_code": etf_code,
        "latest_price": latest_price,
        "iopv": iopv_val,
        "premium_pct": premium_pct,
        "amount": amount,
        "data_quality": data_quality,
        "iopv_source": iopv_source,
        "manual_iopv_updated_date": (manual_iopv or {}).get("updated_date"),
        "iopv_est": (iopv_est_pack or {}).get("iopv_est"),
        "premium_est": (iopv_est_pack or {}).get("premium_est"),
        "est_confidence": (iopv_est_pack or {}).get("est_confidence"),
    }
    rd["analysis"] = {
        "index_symbol": index_symbol,
        "index_close": close,
        "index_day_ret_pct": day_ret,
        "ma25": ma25,
        "ma25_dev_pct": ma25_dev,
        "rsi14": rsi14,
        "streak_days": streak,
        "streak_return_pct": streak_ret,
        "layer_outputs": [layer_cycle, layer_timing, layer_risk],
        "decision_options": decision_options,
        "gates_triggered": layer_risk.get("gate_hits") or [],
        "user_decision_note": "本系统仅提供多视角信息，不替代你的最终交易决策。",
        "risk_notices": risk_notices,
        "manager_premium_notice": manager_notice,
    }
    td_reasons = layer_timing.get("reasons") if isinstance(layer_timing.get("reasons"), list) else []
    if "过热/连续上涨" in td_reasons:
        rd["analysis"]["indicator_opinion"] = "短线过热，当前以持有/减仓为主，不建议追高加仓。"
        # 过热状态下风险层强制禁买，避免与节奏层结论冲突
        layer_risk["options"] = ["hold", "reduce", "exit_wait"]
        rd["analysis"]["decision_options"] = _resolve_decision_options(layer_cycle, layer_timing, layer_risk, cfg)
    rd["risk_notice_rules"] = {"messages": risk_notices}
    rd["tail_decision_mode"] = str(cfg.get("decision_mode") or "user_final_decision")

    if errors:
        rd["runner_errors"] = errors
    return rd, errors


def tool_run_tail_session_analysis_and_send(
    mode: str = "prod",
    fetch_mode: str = "production",
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
    split_markdown_sections: bool = True,
    max_chars_per_message: Optional[int] = None,
) -> Dict[str, Any]:
    from plugins.notification.send_analysis_report import tool_send_analysis_report

    report_data, _ = build_tail_session_report_data(fetch_mode=fetch_mode)
    out = tool_send_analysis_report(
        report_data=report_data,
        mode=mode,
        webhook_url=webhook_url,
        secret=secret,
        keyword=keyword,
        split_markdown_sections=split_markdown_sections,
        max_chars_per_message=max_chars_per_message,
    )
    if isinstance(out, dict):
        data = dict(out.get("data") or {})
        data["report_type"] = "tail_session"
        data["runner_errors"] = report_data.get("runner_errors") or []
        out["data"] = data
    return out

