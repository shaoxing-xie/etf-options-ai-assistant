"""
板块热度评分（0-100）与周期阶段。
结合涨停股列表 + 板块轮动数据，按研究文档规则计算热度与 phase。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _score_limit_up_count(n: int) -> int:
    """涨停股数量 0-30分：≥5只=30，≥3只=20，<3只=10"""
    if n >= 5:
        return 30
    if n >= 3:
        return 20
    if n >= 1:
        return 10
    return 0


def _score_change_pct(pct: Optional[float]) -> int:
    """板块涨幅 0-20分：>3%=20，1-3%=10，<1%=0"""
    if pct is None:
        return 0
    if pct > 3:
        return 20
    if pct >= 1:
        return 10
    return 0


def _score_leader_continuous(max_continuous: Optional[int]) -> int:
    """龙头连板数 0-20分：3连板=20，2连板=15，首板=10"""
    if max_continuous is None or max_continuous < 1:
        return 10
    if max_continuous >= 3:
        return 20
    if max_continuous >= 2:
        return 15
    return 10


def _score_net_inflow(net: Optional[float]) -> int:
    """资金净流入 0-20分：大额=20，小幅=10。单位：元，1亿=1e8"""
    if net is None:
        return 0
    if net >= 1e8:  # 1亿
        return 20
    if net > 0:
        return 10
    return 0


def _infer_phase(score: int, limit_up_count: int, max_continuous: int) -> str:
    """
    板块周期阶段：启动/发酵/高潮/分歧/退潮
    启发式，无历史时仅基于当日数据。
    """
    if limit_up_count < 2:
        return "退潮"
    if score >= 70 and limit_up_count >= 5:
        return "高潮"
    if max_continuous >= 2 and limit_up_count >= 3:
        return "发酵"
    if limit_up_count >= 3 and max_continuous <= 1 and score >= 50:
        return "启动"
    if score >= 50:
        return "分歧"
    return "退潮"


def _match_sector_to_board(sector_name: str, board_name: str) -> bool:
    """板块名称匹配（东方财富行业 vs 涨停池所属行业可能不完全一致）"""
    a, b = sector_name.strip(), board_name.strip()
    if a == b:
        return True
    if a in b or b in a:
        return True
    # 常见映射
    if a in ("电气设备", "电力设备") and b in ("电网设备", "电力", "其他电源"):
        return True
    if a in ("计算机", "电子") and b in ("IT服务Ⅱ", "软件开发", "元件"):
        return True
    return False


def tool_sector_heat_score(
    date: Optional[str] = None,
    limit_up_data: Optional[List[Dict[str, Any]]] = None,
    sector_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    计算各板块热度评分（0-100）与周期阶段。
    若未传 limit_up_data，则内部调用 tool_fetch_limit_up_stocks(date)。
    若未传 sector_data，则内部调用 tool_fetch_sector_data(industry)。
    返回: success, date, sectors: [{ name, score, limit_up_count, avg_change, net_flow, phase, leaders }]
    """
    from data_collection.limit_up.fetch_limit_up import tool_fetch_limit_up_stocks
    from data_collection.sector import tool_fetch_sector_data

    dt = date or datetime.now().strftime("%Y%m%d")
    if limit_up_data is None:
        out = tool_fetch_limit_up_stocks(date=dt)
        if not out.get("success") or not out.get("data"):
            return {
                "success": False,
                "error": "无法获取涨停股数据",
                "date": dt,
                "sectors": [],
            }
        limit_up_data = out["data"]

    # 按板块聚合
    by_board: Dict[str, List[Dict]] = defaultdict(list)
    for r in limit_up_data:
        board = (r.get("board_name") or "").strip() or "其他"
        by_board[board].append(r)

    if sector_data is None:
        sector_data = tool_fetch_sector_data(sector_type="industry", period="today")
    sector_list: List[Dict] = []
    if sector_data.get("status") == "success":
        for x in sector_data.get("all_data", []) or []:
            sector_list.append({
                "sector_name": x.get("sector_name", ""),
                "change_percent": x.get("change_percent"),
                "net_inflow": x.get("net_inflow"),
            })

    # 为每个有涨停的板块计算得分
    result_sectors = []
    for board_name, stocks in by_board.items():
        count = len(stocks)
        max_continuous = max((s.get("continuous_limit_up_count") or 0) for s in stocks) if stocks else 0
        avg_change = sum((s.get("change_pct") or 0) for s in stocks) / count if count else 0

        # 匹配板块轮动数据
        change_pct = None
        net_inflow = None
        for s in sector_list:
            if _match_sector_to_board(s.get("sector_name", ""), board_name):
                change_pct = s.get("change_percent")
                net_inflow = s.get("net_inflow")
                break

        score = min(100, (
            _score_limit_up_count(count)
            + _score_change_pct(change_pct)
            + _score_leader_continuous(max_continuous if max_continuous else None)
            + _score_net_inflow(net_inflow)
            + 0  # 消息催化暂无
        ))
        phase = _infer_phase(score, count, max_continuous or 0)

        # 龙头候选：连板数优先，其次涨停越早越好，再次流通市值 30–80 亿优先
        def _leader_key(s: Dict) -> tuple:
            cont = s.get("continuous_limit_up_count") or 0
            t = s.get("limit_up_time") or "99:99:99"
            mv = s.get("float_mv") or 0
            mv_ok = 1 if 3e9 <= mv <= 8e9 else 0
            return (-cont, t, -mv_ok, -min(mv, 8e9) if mv else 0)

        sorted_stocks = sorted(stocks, key=_leader_key)
        leaders = sorted_stocks[:3]

        result_sectors.append({
            "name": board_name,
            "score": score,
            "limit_up_count": count,
            "avg_change": round(avg_change, 2),
            "net_flow": net_inflow,
            "phase": phase,
            "max_continuous": max_continuous,
            "leaders": [
                {
                    "code": s.get("code"),
                    "name": s.get("name"),
                    "limit_up_time": s.get("limit_up_time"),
                    "continuous_limit_up_count": s.get("continuous_limit_up_count"),
                    "float_mv": s.get("float_mv"),
                    "turnover_rate": s.get("turnover_rate"),
                }
                for s in leaders
            ],
        })

    # 按得分排序
    result_sectors.sort(key=lambda x: -x["score"])

    return {
        "success": True,
        "date": dt,
        "sectors": result_sectors,
    }
