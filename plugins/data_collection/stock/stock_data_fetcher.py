"""
个股数据采集与聚合工具

提供：
1) tool_stock_data_fetcher：批量拉取行情/日线/分钟线/财务并可选计算技术指标
2) tool_stock_monitor：watchlist 触发器的一次性检查 + 可选通知发送

注意：
- 底层数据采集继续复用现有 tools：tool_fetch_stock_realtime / tool_fetch_stock_historical / tool_fetch_stock_minute / tool_fetch_stock_financials。
- 技术指标计算复用 plugins/analysis/technical_indicators.py 的工具逻辑。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


def _normalize_symbols(symbols: Any) -> List[str]:
    if symbols is None:
        return []
    if isinstance(symbols, str):
        raw = [s.strip() for s in symbols.replace(";", ",").split(",") if s.strip()]
    elif isinstance(symbols, (list, tuple)):
        raw = [str(s).strip() for s in symbols if str(s).strip()]
    else:
        raw = [str(symbols).strip()]
    # dedup preserve order
    seen = set()
    out: List[str] = []
    for s in raw:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _parse_minute_periods(minute_period: str) -> List[str]:
    if not minute_period:
        return ["5"]
    ps = [p.strip() for p in str(minute_period).replace(";", ",").split(",") if p.strip()]
    # 保持工具支持范围
    allowed = {"5", "15", "30", "60", "1"}
    ps2: List[str] = []
    for p in ps:
        if p in allowed:
            ps2.append(p)
    return ps2 or ["5"]


def _safe_get(d: Any, key: str, default: Any = None) -> Any:
    if isinstance(d, dict):
        return d.get(key, default)
    return default


def _extract_minute_klines_by_period(minute_fetch_res: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = minute_fetch_res.get("data") if isinstance(minute_fetch_res, dict) else None
    if not isinstance(data, dict):
        return []
    klines = data.get("klines")
    if isinstance(klines, list):
        return klines
    return []


def _compute_technicals_from_klines(
    *,
    symbol: str,
    klines: List[Dict[str, Any]],
    minute_period: str,
    indicators: List[str],
) -> Dict[str, Any]:
    """
    复用 tool_calculate_technical_indicators：传入 klines_data 直接计算，绕过 cache 读取。
    """
    try:
        from plugins.analysis.technical_indicators import tool_calculate_technical_indicators

        # data_type 对 technical_indicators 主要用于 cache；传 klines_data 会优先使用传入数据。
        # minute klines 的字段是：time/open/close/high/low/volume/amount/change_percent
        res = tool_calculate_technical_indicators(
            symbol=symbol,
            data_type="index_minute",
            period=minute_period,
            indicators=indicators,
            lookback_days=120,
            klines_data=klines,
        )
        return res
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"calculate technicals failed: {e}", "data": None}


def tool_stock_data_fetcher(
    action: str = "fetch",
    symbols: Any = None,
    data_types: Optional[List[str]] = None,
    minute_period: str = "5,15,30",
    lookback_days: int = 20,
    indicators: Optional[List[str]] = None,
    include_analysis: bool = False,
    mode: str = "production",
) -> Dict[str, Any]:
    """
    个股数据聚合器（最小可用版）：
    - action="fetch": 拉取数据并可选计算技术指标/简单综合分析
    """
    try:
        if action != "fetch":
            return {
                "success": False,
                "message": f"unsupported action: {action}",
                "data": None,
            }

        sym_list = _normalize_symbols(symbols)
        if not sym_list:
            return {"success": False, "message": "symbols 不能为空", "data": None}

        if data_types is None:
            data_types = ["realtime", "daily", "minute", "financials", "technicals"]
        indicators = indicators or ["ma", "macd", "rsi", "bollinger"]

        minute_periods = _parse_minute_periods(minute_period)

        # ---- 财务：一次性批量请求（复用已有工具）----
        financials_map: Dict[str, Dict[str, Any]] = {}
        if "financial" in ",".join(data_types) or "financials" in data_types or "financial" in data_types:
            from plugins.data_collection.financials import tool_fetch_stock_financials

            fin_res = tool_fetch_stock_financials(symbols=",".join(sym_list), lookback_report_count=1)
            for rec in fin_res.get("financials", []) if isinstance(fin_res, dict) else []:
                if isinstance(rec, dict) and rec.get("symbol"):
                    financials_map[str(rec["symbol"])] = rec

        results: List[Dict[str, Any]] = []

        # ---- 主循环：逐只股票拉取 ----
        for sym in sym_list:
            item: Dict[str, Any] = {"symbol": sym}
            realtime = None
            daily = None
            minute_data: Dict[str, Any] = {}
            technicals: Dict[str, Any] = {}

            # realtime
            if "realtime" in data_types or "real_time" in data_types:
                from plugins.data_collection.stock.fetch_realtime import tool_fetch_stock_realtime

                rt_res = tool_fetch_stock_realtime(stock_code=sym, mode=mode)
                realtime = rt_res.get("data")
                item["realtime"] = realtime
                item["realtime_fetch"] = {"success": rt_res.get("success"), "source": rt_res.get("source")}
            # daily history
            if "daily" in data_types or "historical" in data_types:
                from plugins.data_collection.stock.fetch_historical import tool_fetch_stock_historical

                daily_res = tool_fetch_stock_historical(
                    stock_code=sym,
                    period="daily",
                    lookback_days=lookback_days,
                    use_cache=True,
                )
                daily = daily_res.get("data", {}).get("klines") if isinstance(daily_res.get("data"), dict) else None
                item["daily_hist"] = daily
                item["daily_fetch"] = {"success": daily_res.get("success"), "source": daily_res.get("source")}
            # minute klines
            if "minute" in data_types:
                from plugins.data_collection.stock.fetch_minute import tool_fetch_stock_minute

                for p in minute_periods:
                    m_res = tool_fetch_stock_minute(
                        stock_code=sym,
                        period=p,
                        lookback_days=max(5, lookback_days // 4),
                        mode=mode,
                        use_cache=True,
                    )
                    klines = None
                    if isinstance(m_res, dict) and isinstance(m_res.get("data"), dict):
                        klines = m_res["data"].get("klines")
                    minute_data[p] = klines or []
                    technicals_key = f"{p}min"
                    item.setdefault("minute_fetch", {})[p] = {
                        "success": m_res.get("success"),
                        "returned_count": (m_res.get("data") or {}).get("returned_count"),
                        "source": m_res.get("source"),
                    }

                    # technicals per period (可选)
                    if "technicals" in data_types:
                        tech_res = _compute_technicals_from_klines(
                            symbol=sym,
                            klines=minute_data[p],
                            minute_period=p,
                            indicators=indicators,
                        )
                        technicals[technicals_key] = tech_res

            if "financials" in data_types or "financial" in data_types:
                item["financials"] = financials_map.get(sym)

            if include_analysis:
                # 简单综合：仅用 5min 技术信号 + 财务估值
                analysis: Dict[str, Any] = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "signals": [],
                    "score": 0,
                }
                # 技术信号
                tech5 = technicals.get("5min") or next(iter(technicals.values()), None)
                if isinstance(tech5, dict) and tech5.get("success") and isinstance(tech5.get("data"), dict):
                    signal = tech5["data"].get("signal", {})
                    if isinstance(signal, dict):
                        analysis["signals"] = signal.get("signals", []) or []
                        summary = signal.get("summary", "")
                        analysis["signal_summary"] = summary
                    # heuristic score
                    score = 0
                    for s in analysis["signals"]:
                        s2 = str(s)
                        if "金叉" in s2 or "多头排列" in s2:
                            score += 20
                        if "死叉" in s2 or "空头排列" in s2:
                            score -= 20
                        if "RSI超买" in s2:
                            score -= 10
                        if "RSI超卖" in s2:
                            score += 10
                    analysis["score"] = score

                # 估值因子（如果有）
                fin = financials_map.get(sym) if isinstance(financials_map, dict) else None
                if isinstance(fin, dict):
                    pe = fin.get("pe_ttm")
                    pb = fin.get("pb")
                    roe = fin.get("roe")
                    analysis["valuation"] = {"pe_ttm": pe, "pb": pb, "roe": roe}
                    # 简单 heuristic：pe/pb 越低分数越高（仅示意）
                    if isinstance(pe, (int, float)) and pe > 0:
                        analysis["score"] += max(-10, min(10, 10 - pe / 5))
                    if isinstance(pb, (int, float)) and pb > 0:
                        analysis["score"] += max(-10, min(10, 10 - pb))

                item["analysis"] = analysis

            # 统一输出
            if "realtime" in data_types:
                item["realtime"] = realtime
            if "daily" in data_types:
                item["daily_hist"] = daily
            if "minute" in data_types:
                item["minute_data"] = minute_data
            if "technicals" in data_types:
                item["technicals"] = technicals

            results.append(item)

        # success：只要有任意一只拿到 realtime/daily/minute/technicals 的非空数据就算部分成功
        success_any = False
        for r in results:
            if r.get("realtime") or (r.get("daily_hist") or []) or any(v for v in (r.get("minute_data") or {}).values()):
                success_any = True
                break

        return {
            "success": success_any,
            "message": "Fetched stock data" if success_any else "Fetched but empty data",
            "data": results[0] if len(results) == 1 else results,
            "count": len(results),
        }

    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"tool_stock_data_fetcher error: {e}", "data": None}


def tool_stock_monitor(
    action: str = "run_once",
    watchlist: Optional[List[str]] = None,
    triggers: Optional[List[Dict[str, Any]]] = None,
    output_channel: str = "feishu",
    cooldown_minutes: int = 30,
    mode: str = "production",
    state_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    股票监控工具（可配）：一次性检查 watchlist 是否满足触发器。

    说明：
    - action="start": 保存监控配置，并可选择立即 run_once（本实现默认立即检查）。
    - action="stop": 关闭（删除配置文件，或标记 disabled）
    - action="status": 返回配置文件内容
    - action="run_once": 直接检查（如果 watchlist/triggers 未传则使用 state）
    """
    try:
        from plugins.notification.notification_cooldown import should_send, record_send

        if state_path is None:
            state_path = os.path.expanduser("~/.openclaw/workspace/stock_monitor_state.json")

        def _load_state() -> Dict[str, Any]:
            if not os.path.exists(state_path):
                return {}
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    obj = json.load(f)
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}

        def _save_state(obj: Dict[str, Any]) -> None:
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)

        if action == "status":
            state = _load_state()
            return {"success": True, "data": state, "message": "status"}

        if action == "stop":
            if os.path.exists(state_path):
                try:
                    os.remove(state_path)
                except Exception:
                    # fallback: mark disabled
                    _save_state({"disabled": True})
            return {"success": True, "message": "stopped"}

        # start: 保存配置 + run_once
        if action == "start":
            if not watchlist:
                return {"success": False, "message": "start requires watchlist", "data": None}
            if triggers is None:
                triggers = []
            _save_state(
                {
                    "disabled": False,
                    "watchlist": watchlist,
                    "triggers": triggers,
                    "output_channel": output_channel,
                    "cooldown_minutes": cooldown_minutes,
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            # fallthrough -> run once

        state = _load_state()
        if watchlist is None:
            watchlist = state.get("watchlist")
        if triggers is None:
            triggers = state.get("triggers")
        if output_channel is None:
            output_channel = state.get("output_channel", "feishu")
        if cooldown_minutes is None:
            cooldown_minutes = int(state.get("cooldown_minutes", 30))

        watchlist = watchlist or []
        triggers = triggers or []

        if state.get("disabled"):
            return {"success": True, "skipped": True, "message": "monitor disabled"}

        if not watchlist:
            return {"success": False, "message": "watchlist is empty", "data": None}

        # ---- 拉取必要数据：realtime +（用于量能突增）minute ----
        from plugins.data_collection.stock.fetch_realtime import tool_fetch_stock_realtime
        from plugins.data_collection.stock.fetch_minute import tool_fetch_stock_minute

        fired: List[Dict[str, Any]] = []

        for sym in watchlist:
            rt_res = tool_fetch_stock_realtime(stock_code=sym, mode=mode)
            rt = rt_res.get("data") if isinstance(rt_res, dict) else None
            if not isinstance(rt, dict):
                continue

            current_price = float(rt.get("current_price") or 0.0)
            change_pct = float(rt.get("change_percent") or 0.0)
            volume_now = float(rt.get("volume") or 0.0)

            # volume_surge：用 5min 最近 N 根的均值对比（更稳）
            vol_surge_stats: Optional[Tuple[float, float, int]] = None
            need_minute = any((t or {}).get("type") == "volume_surge" for t in triggers)
            if need_minute:
                m_res = tool_fetch_stock_minute(
                    stock_code=sym,
                    period="5",
                    lookback_days=5,
                    mode=mode,
                    use_cache=True,
                )
                klines = (m_res.get("data") or {}).get("klines") if isinstance(m_res, dict) else None
                if isinstance(klines, list) and klines:
                    # last bar
                    last_bar = klines[-1]
                    last_vol = float(last_bar.get("volume") or 0.0)
                    # avg previous 10 bars
                    prev = klines[-11:-1] if len(klines) > 10 else klines[:-1]
                    avg_vol = sum(float(b.get("volume") or 0.0) for b in prev) / max(1, len(prev))
                    vol_surge_stats = (last_vol, avg_vol, len(prev))

            for t in triggers:
                if not isinstance(t, dict):
                    continue
                t_type = t.get("type")
                symbol_in_trigger = t.get("symbol")
                if symbol_in_trigger and str(symbol_in_trigger) != str(sym):
                    continue

                if t_type == "price_change":
                    pct = float(t.get("pct") or t.get("threshold") or 0.0)
                    if pct <= 0:
                        continue
                    if abs(change_pct) >= pct:
                        fired.append(
                            {
                                "symbol": sym,
                                "type": t_type,
                                "value": change_pct,
                                "pct": pct,
                                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            }
                        )
                elif t_type == "volume_surge":
                    ratio = float(t.get("ratio") or t.get("threshold") or 0.0)
                    if ratio <= 0:
                        continue
                    if not vol_surge_stats:
                        continue
                    last_vol, avg_vol, _n = vol_surge_stats
                    if avg_vol <= 0:
                        continue
                    cur_ratio = last_vol / avg_vol
                    if cur_ratio >= ratio:
                        fired.append(
                            {
                                "symbol": sym,
                                "type": t_type,
                                "value": cur_ratio,
                                "ratio": ratio,
                                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            }
                        )
                elif t_type == "support_break":
                    level = float(t.get("level") or t.get("threshold") or 0.0)
                    if level <= 0:
                        continue
                    if current_price <= level:
                        fired.append(
                            {
                                "symbol": sym,
                                "type": t_type,
                                "value": current_price,
                                "level": level,
                                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            }
                        )

        # ---- 通知发送（仅飞书工具支持）----
        notifications: List[Dict[str, Any]] = []
        if fired:
            # 组织一条消息（简单）
            lines = [f"股票监控触发 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"]
            for e in fired:
                lines.append(f"- {e['symbol']} | {e['type']} | value={e.get('value')} | rule={e.get('pct') or e.get('ratio') or e.get('level')}")
            msg = "\n".join(lines)

            if str(output_channel).lower() in {"feishu", "flk", "feishu_card", "feishu_message"}:
                from plugins.notification.send_feishu_message import tool_send_feishu_message

                # cooldown 去重：按全部触发 key
                key = f"stock_monitor:{','.join([str(x.get('symbol')) for x in fired])}:{len(fired)}"
                decision = should_send(key=key, cooldown_minutes=int(cooldown_minutes))
                if decision.allowed:
                    send_res = tool_send_feishu_message(message=msg, title="Stock Monitor")
                    if send_res.get("success"):
                        record_send(key=key)
                    notifications.append({"channel": "feishu", "send_result": send_res})
                else:
                    notifications.append({"channel": "feishu", "skipped": True, "reason": decision.reason})
            elif str(output_channel).lower() in {"dingtalk", "ding", "钉钉"}:
                from plugins.notification.send_dingtalk_message import tool_send_dingtalk_message

                key = f"stock_monitor:{','.join([str(x.get('symbol')) for x in fired])}:{len(fired)}"
                decision = should_send(key=key, cooldown_minutes=int(cooldown_minutes))
                if decision.allowed:
                    send_res = tool_send_dingtalk_message(
                        message=msg,
                        title="Stock Monitor",
                        mode=mode,
                    )
                    if send_res.get("success") and not send_res.get("skipped"):
                        record_send(key=key)
                    notifications.append({"channel": "dingtalk", "send_result": send_res})
                else:
                    notifications.append({"channel": "dingtalk", "skipped": True, "reason": decision.reason})
            else:
                notifications.append(
                    {
                        "channel": output_channel,
                        "skipped": True,
                        "reason": "dingtalk send tool not found; returning fired events only",
                    }
                )

        return {
            "success": True,
            "data": {
                "fired": fired,
                "notifications": notifications,
                "watchlist_count": len(watchlist),
                "trigger_count": len(triggers),
            },
            "message": "monitor check finished",
        }

    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"tool_stock_monitor error: {e}", "data": None}

