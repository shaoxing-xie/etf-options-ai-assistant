"""
涨停回马枪策略回测：通用引擎 + 策略规则编码（次日低吸、3-5日回调、双底）。
输入：日度 limit_up_with_sector 数据；通过历史日线模拟成交与收益。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "limit_up_research"


def _normalize_sector_keywords(sector_keywords: Any) -> Optional[List[str]]:
    """Accept list, comma/Chinese-comma separated str, or None."""
    if sector_keywords is None:
        return None
    if isinstance(sector_keywords, str):
        s = sector_keywords.replace("，", ",")
        out = [p.strip() for p in s.split(",") if p.strip()]
        return out or None
    if isinstance(sector_keywords, (list, tuple)):
        out = [str(x).strip() for x in sector_keywords if str(x).strip()]
        return out or None
    return None


def _sector_board_matches_keywords(board_name: str, keywords: List[str]) -> bool:
    bn = board_name or ""
    for kw in keywords:
        if not kw:
            continue
        if kw in bn:
            return True
        try:
            if kw.casefold() in bn.casefold():
                return True
        except Exception:
            pass
    return False


@dataclass
class BacktestOrder:
    """虚拟订单"""
    symbol: str
    name: str
    strategy: str
    entry_date: str  # YYYYMMDD
    entry_price: float
    stop_loss: float
    target: float
    hold_days: int
    sector: str
    phase: str
    is_leader: bool = True


@dataclass
class BacktestTrade:
    """成交记录"""
    exit_date: str
    exit_price: float
    exit_reason: str  # "stop_loss" | "target" | "hold_end"
    pnl_pct: float
    hold_days_actual: int
    order: Optional[BacktestOrder] = None


def _load_payloads(data_dir: Path, start_date: Optional[str], end_date: Optional[str]) -> Dict[str, Dict]:
    """加载 data/limit_up_research 下 YYYYMMDD_limit_up_with_sector.json，返回 date_str -> payload"""
    out = {}
    for f in sorted(data_dir.glob("*_limit_up_with_sector.json")):
        try:
            stem = f.stem.replace("_limit_up_with_sector", "")
            if len(stem) != 8 or not stem.isdigit():
                continue
            if start_date and stem < start_date:
                continue
            if end_date and stem > end_date:
                continue
            with open(f, "r", encoding="utf-8") as fp:
                out[stem] = json.load(fp)
        except Exception as e:
            logger.warning("跳过 %s: %s", f.name, e)
    return out


def _fetch_stock_daily(symbol: str, start_yyyymmdd: str, end_yyyymmdd: str) -> Optional[List[Dict]]:
    """获取股票日线 [日期(YYYYMMDD), 开盘, 收盘, 最高, 最低, 成交量]，失败返回 None"""
    try:
        import akshare as ak
        # akshare 需要 19700101 格式
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_yyyymmdd,
            end_date=end_yyyymmdd,
            adjust="qfq",
        )
        if df is None or df.empty:
            return None
        rows = []
        for _, r in df.iterrows():
            d = r.get("日期")
            if hasattr(d, "strftime"):
                d = d.strftime("%Y%m%d")
            else:
                d = str(d).replace("-", "")[:8]
            rows.append({
                "date": d,
                "open": float(r.get("开盘", 0)),
                "close": float(r.get("收盘", 0)),
                "high": float(r.get("最高", 0)),
                "low": float(r.get("最低", 0)),
                "volume": float(r.get("成交量", 0)),
            })
        return rows
    except Exception as e:
        logger.debug("fetch %s failed: %s", symbol, e)
        return None


def _simulate_order(
    bars: List[Dict],
    entry_date: str,
    entry_price: float,
    stop_loss: float,
    target: float,
    hold_days: int,
) -> Optional[BacktestTrade]:
    """
    用日线模拟：从 entry_date 起 hold_days 内，若当日最低<=止损则止损；若当日最高>=目标则止盈；否则持仓到期按收盘价平仓。
    bars 按 date 升序，且包含 entry_date 及之后若干天。
    """
    by_date = {b["date"]: b for b in bars}
    dates = sorted([b["date"] for b in bars])
    if entry_date not in by_date:
        return None
    idx = dates.index(entry_date)
    window = dates[idx : idx + hold_days + 1]
    for i, d in enumerate(window):
        b = by_date.get(d)
        if not b:
            continue
        low, high = b["low"], b["high"]
        if low <= stop_loss:
            return BacktestTrade(
                exit_date=d,
                exit_price=stop_loss,
                exit_reason="stop_loss",
                pnl_pct=(stop_loss - entry_price) / entry_price * 100,
                hold_days_actual=i,
            )
        if high >= target:
            return BacktestTrade(
                exit_date=d,
                exit_price=target,
                exit_reason="target",
                pnl_pct=(target - entry_price) / entry_price * 100,
                hold_days_actual=i,
            )
    # 持仓到期
    last_d = window[-1]
    last_b = by_date.get(last_d)
    exit_price = last_b["close"] if last_b else entry_price
    return BacktestTrade(
        exit_date=last_d,
        exit_price=exit_price,
        exit_reason="hold_end",
        pnl_pct=(exit_price - entry_price) / entry_price * 100,
        hold_days_actual=len(window) - 1,
    )


# --------------- 策略规则：次日低吸（启动期龙头） ---------------
def select_next_day_dip_candidates(
    payload_prev: Dict,
    sector_score_min: int = 70,
    phase: str = "启动",
) -> List[Dict]:
    """
    从 T-1 日的 limit_up_with_sector 中选出「次日低吸」候选：板块 phase==启动、score>=70 的龙头。
    返回 list of { code, name, board_name, limit_up_close, limit_up_low, sector_score, phase, leader_score }
    """
    candidates = []
    for sec in payload_prev.get("sectors") or []:
        if sec.get("phase") != phase or (sec.get("score") or 0) < sector_score_min:
            continue
        for L in sec.get("leaders") or []:
            code = L.get("code")
            if not code:
                continue
            # limit_up 日收盘用 latest_price
            limit_up_close = L.get("latest_price") or 0
            if not limit_up_close and payload_prev.get("limit_up_list"):
                for r in payload_prev["limit_up_list"]:
                    if r.get("code") == code:
                        limit_up_close = r.get("latest_price") or 0
                        break
            candidates.append({
                "code": code,
                "name": L.get("name", ""),
                "board_name": sec.get("name", ""),
                "limit_up_close": limit_up_close,
                "limit_up_low": None,  # 需从日线补
                "sector_score": sec.get("score", 0),
                "phase": sec.get("phase", ""),
                "leader_score": L.get("leader_score", 0),
            })
    return candidates


def run_next_day_dip(
    payload_prev: Dict,
    payload_today: Optional[Dict],
    order_date: str,
    dip_open_pct_min: float = -5.0,
    dip_open_pct_max: float = -2.0,
    volume_shrink_ratio: float = 1.0,
    stop_loss_below_limit_pct: float = 5.0,
    target_pct: float = 5.0,
    hold_days: int = 5,
    sector_score_min: int = 70,
    fetch_daily: bool = True,
    sector_keywords: Optional[List[str]] = None,
) -> List[BacktestTrade]:
    """
    次日低吸回测：T-1 涨停+启动期+热度>=70 → T 日低开 2-5%、量萎缩 → 以 T 日开盘价买入，止损/目标/持仓日数。
    若 fetch_daily 为 True，会请求 akshare 获取日线并模拟；否则返回空列表。
    """
    candidates = select_next_day_dip_candidates(payload_prev, sector_score_min=sector_score_min, phase="启动")
    if sector_keywords:
        candidates = [
            c
            for c in candidates
            if _sector_board_matches_keywords(c.get("board_name", ""), sector_keywords)
        ]
    if not candidates:
        return []
    trades = []
    start = order_date
    end_dt = datetime.strptime(order_date, "%Y%m%d") + timedelta(days=hold_days + 5)
    end = end_dt.strftime("%Y%m%d")
    for c in candidates:
        code = c["code"]
        limit_close = c["limit_up_close"]
        if not limit_close or limit_close <= 0:
            continue
        if not fetch_daily:
            continue
        # 需要 T-1 的 low 做止损；T 日 open 做入场
        prev_date = (datetime.strptime(order_date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        bars = _fetch_stock_daily(code, prev_date, end)
        if not bars:
            continue
        by_d = {b["date"]: b for b in bars}
        prev_bar = by_d.get(prev_date)
        t_bar = by_d.get(order_date)
        if not t_bar:
            continue
        limit_low = prev_bar["low"] if prev_bar else limit_close * 0.95
        open_price = t_bar["open"]
        dip_pct = (open_price - limit_close) / limit_close * 100
        if dip_pct > dip_open_pct_max or dip_pct < dip_open_pct_min:
            continue
        if prev_bar and volume_shrink_ratio < 1.0 and t_bar["volume"] > 0 and prev_bar["volume"] > 0:
            if t_bar["volume"] / prev_bar["volume"] > volume_shrink_ratio:
                continue
        stop_loss = min(limit_low, limit_close * (1 - stop_loss_below_limit_pct / 100))
        target_price = limit_close * (1 + target_pct / 100)
        order = BacktestOrder(
            symbol=code,
            name=c["name"],
            strategy="next_day_dip",
            entry_date=order_date,
            entry_price=open_price,
            stop_loss=stop_loss,
            target=target_price,
            hold_days=hold_days,
            sector=c["board_name"],
            phase=c["phase"],
            is_leader=True,
        )
        trade = _simulate_order(bars, order_date, open_price, stop_loss, target_price, hold_days)
        if trade:
            trade.order = order
            trades.append(trade)
    return trades


# --------------- 策略规则：3-5 日回调（发酵期龙头） ---------------
def select_pullback_3_5_candidates(
    payload_prev: Dict,
    sector_score_min: int = 60,
    phase: str = "发酵",
) -> List[Dict]:
    """涨停后 3-5 日内回调 5-10% 的发酵期龙头，需结合多日数据筛选，这里仅从单日 payload 取候选（后续由引擎按日线判断回调）。"""
    candidates = []
    for sec in payload_prev.get("sectors") or []:
        if sec.get("phase") != phase or (sec.get("score") or 0) < sector_score_min:
            continue
        for L in sec.get("leaders") or []:
            if L.get("code"):
                candidates.append({
                    "code": L["code"],
                    "name": L.get("name", ""),
                    "board_name": sec.get("name", ""),
                    "limit_up_close": L.get("latest_price") or 0,
                    "sector_score": sec.get("score", 0),
                    "phase": sec.get("phase", ""),
                })
    return candidates


# --------------- 回测入口 ---------------
def run_backtest(
    data_dir: Optional[Path] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    strategies: Optional[List[str]] = None,
    **strategy_params: Any,
) -> Dict[str, Any]:
    """
    回测主入口。
    - data_dir: 存放 YYYYMMDD_limit_up_with_sector.json 的目录
    - start_date / end_date: YYYYMMDD
    - strategies: ["next_day_dip"] 等，默认只跑次日低吸
    返回: { success, trades, stats, params }
    """
    data_dir = data_dir or DEFAULT_DATA_DIR
    if not data_dir.exists():
        return {
            "success": False,
            "error": f"数据目录不存在: {data_dir}",
            "trades": [],
            "stats": {},
        }
    payloads = _load_payloads(data_dir, start_date, end_date)
    if len(payloads) < 2:
        return {
            "success": False,
            "error": "至少需要连续两日数据才能运行次日低吸回测",
            "trades": [],
            "stats": {},
        }
    strategies = strategies or ["next_day_dip"]
    dates = sorted(payloads.keys())
    all_trades: List[BacktestTrade] = []
    for i in range(1, len(dates)):
        t_date = dates[i]
        prev_date = dates[i - 1]
        payload_prev = payloads[prev_date]
        payload_t = payloads.get(t_date)
        if "next_day_dip" in strategies:
            kw = _normalize_sector_keywords(strategy_params.get("sector_keywords"))
            trades = run_next_day_dip(
                payload_prev,
                payload_t,
                order_date=t_date,
                sector_score_min=int(strategy_params.get("sector_score_min", 70)),
                hold_days=int(strategy_params.get("hold_days", 5)),
                stop_loss_below_limit_pct=float(strategy_params.get("stop_loss_below_limit_pct", 5)),
                target_pct=float(strategy_params.get("target_pct", 5)),
                fetch_daily=True,
                sector_keywords=kw,
            )
            all_trades.extend(trades)
    # 统计：胜率、平均盈亏、盈亏比、最大回撤、交易次数、持仓分布
    if not all_trades:
        stats = {
            "win_count": 0, "total_count": 0, "win_rate": 0, "avg_pnl_pct": 0,
            "profit_factor": 0.0, "max_drawdown_pct": 0, "hold_days_dist": {},
        }
    else:
        pnls = [t.pnl_pct for t in all_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 1
        profit_factor = (avg_win / avg_loss * len(wins) / len(losses)) if losses and avg_loss else (float("inf") if wins else 0)
        hold_days_dist = {}
        for t in all_trades:
            d = t.hold_days_actual
            hold_days_dist[str(d)] = hold_days_dist.get(str(d), 0) + 1
        stats = {
            "win_count": len(wins),
            "total_count": len(all_trades),
            "win_rate": round(len(wins) / len(all_trades) * 100, 2),
            "avg_pnl_pct": round(sum(pnls) / len(pnls), 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(min(pnls), 2) if pnls else 0,
            "hold_days_dist": hold_days_dist,
        }
    def _trade_to_dict(t: BacktestTrade) -> Dict:
        o = t.order
        return {
            "symbol": o.symbol if o else "",
            "name": o.name if o else "",
            "sector": o.sector if o else "",
            "strategy": o.strategy if o else "",
            "entry_date": o.entry_date if o else "",
            "entry_price": o.entry_price if o else 0,
            "exit_date": t.exit_date,
            "exit_price": t.exit_price,
            "exit_reason": t.exit_reason,
            "pnl_pct": round(t.pnl_pct, 2),
            "hold_days_actual": t.hold_days_actual,
        }
    params_out = {
        "start_date": start_date,
        "end_date": end_date,
        "strategies": strategies,
        **strategy_params,
    }
    nk = _normalize_sector_keywords(strategy_params.get("sector_keywords"))
    if nk is not None:
        params_out["sector_keywords"] = nk

    return {
        "success": True,
        "trades": [_trade_to_dict(t) for t in all_trades],
        "stats": stats,
        "params": params_out,
    }


def tool_backtest_limit_up_pullback(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    data_dir: Optional[str] = None,
    strategies: Optional[List[str]] = None,
    sector_score_min: int = 70,
    hold_days: int = 5,
    stop_loss_below_limit_pct: float = 5.0,
    target_pct: float = 5.0,
    sector_keywords: Any = None,
) -> Dict[str, Any]:
    """
    涨停回马枪回测工具。可被 tool_runner 调用。
    sector_keywords: 仅保留板块名 board_name 命中任一关键词的候选（如军工主题：["军工","国防"]）。
    """
    path = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    kw = _normalize_sector_keywords(sector_keywords)
    return run_backtest(
        data_dir=path,
        start_date=start_date,
        end_date=end_date,
        strategies=strategies or ["next_day_dip"],
        sector_score_min=sector_score_min,
        hold_days=hold_days,
        stop_loss_below_limit_pct=stop_loss_below_limit_pct,
        target_pct=target_pct,
        sector_keywords=kw,
    )


# --------------- 参数敏感性 ---------------
# 推荐默认参数（基于回测与风控平衡，见计划 3.4）
RECOMMENDED_DEFAULT_PARAMS = {
    "sector_score_min": 70,
    "hold_days": 5,
    "stop_loss_below_limit_pct": 5.0,
    "target_pct": 5.0,
    "dip_open_pct_min": -5.0,
    "dip_open_pct_max": -2.0,
}


def run_parameter_sensitivity(
    data_dir: Optional[Path] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    grid: Optional[Dict[str, List[Any]]] = None,
) -> Dict[str, Any]:
    """
    对关键参数做网格搜索，返回每组 stats 及推荐参数。
    grid 示例: {"sector_score_min": [60, 70, 80], "hold_days": [3, 5, 7], "stop_loss_below_limit_pct": [3, 5, 8]}
    """
    data_dir = data_dir or DEFAULT_DATA_DIR
    if not data_dir.exists():
        return {"success": False, "error": f"数据目录不存在: {data_dir}", "grid_results": [], "recommended": RECOMMENDED_DEFAULT_PARAMS}
    grid = grid or {
        "sector_score_min": [60, 70, 80],
        "hold_days": [3, 5, 7],
        "stop_loss_below_limit_pct": [3, 5, 8],
        "target_pct": [3, 5, 8],
    }
    results = []
    for sector_score_min in grid.get("sector_score_min", [70]):
        for hold_days in grid.get("hold_days", [5]):
            for stop_pct in grid.get("stop_loss_below_limit_pct", [5]):
                for target_pct in grid.get("target_pct", [5]):
                    out = run_backtest(
                        data_dir=data_dir,
                        start_date=start_date,
                        end_date=end_date,
                        strategies=["next_day_dip"],
                        sector_score_min=int(sector_score_min),
                        hold_days=int(hold_days),
                        stop_loss_below_limit_pct=float(stop_pct),
                        target_pct=float(target_pct),
                    )
                    if not out.get("success"):
                        continue
                    stats = out.get("stats") or {}
                    # 综合得分：胜率权重 0.5 + 平均盈亏 0.3（正为好）- 回撤 0.2
                    score = (stats.get("win_rate", 0) or 0) * 0.5 + max(0, stats.get("avg_pnl_pct", 0) or 0) * 0.3 - abs(stats.get("max_drawdown_pct", 0) or 0) * 0.2
                    results.append({
                        "params": {
                            "sector_score_min": sector_score_min,
                            "hold_days": hold_days,
                            "stop_loss_below_limit_pct": stop_pct,
                            "target_pct": target_pct,
                        },
                        "stats": stats,
                        "score": round(score, 2),
                    })
    if not results:
        return {
            "success": True,
            "grid_results": [],
            "recommended": RECOMMENDED_DEFAULT_PARAMS,
            "note": "无有效回测结果，请增加数据日期范围",
        }
    best = max(results, key=lambda x: (x["stats"].get("total_count", 0) > 0, x["score"]))
    return {
        "success": True,
        "grid_results": results,
        "recommended": best["params"],
        "best_score": best["score"],
        "default_documentation": RECOMMENDED_DEFAULT_PARAMS,
    }


def tool_backtest_limit_up_sensitivity(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """参数敏感性分析，可被 tool_runner 调用。"""
    path = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    return run_parameter_sensitivity(data_dir=path, start_date=start_date, end_date=end_date)
