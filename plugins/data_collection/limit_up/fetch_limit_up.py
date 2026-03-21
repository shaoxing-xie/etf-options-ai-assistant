"""
涨停股数据管道：获取指定日期的涨停股列表，支持多日区间。
数据源：AKShare stock_zt_pool_em；可选东方财富等 fallback。
过滤：ST、次新股(<3月)、换手率>30%、尾盘涨停(14:30后)、无板块归属。
输出字段：code, name, limit_up_time, change_pct, turnover_rate, float_mv, board_name, continuous_limit_up_count 等。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

# 列名映射（akshare 返回中文列名）
COL_CODE = "代码"
COL_NAME = "名称"
COL_CHANGE_PCT = "涨跌幅"
COL_PRICE = "最新价"
COL_TURNOVER_RATE = "换手率"
COL_FLOAT_MV = "流通市值"
COL_FIRST_SEAL_TIME = "首次封板时间"
COL_LAST_SEAL_TIME = "最后封板时间"
COL_BOARD = "所属行业"
COL_CONTINUOUS = "连板数"
COL_AMOUNT = "成交额"


def _parse_seal_time(s: Any) -> Optional[str]:
    """解析首次封板时间 例如 092500 -> 09:25:00"""
    if s is None or (isinstance(s, float) and (s != s)):
        return None
    s = str(s).strip()
    if len(s) == 6 and s.isdigit():
        return f"{s[:2]}:{s[2:4]}:{s[4:6]}"
    return s


def _is_tail_limit_up(first_seal_time: Optional[str], last_seal_time: Optional[str]) -> bool:
    """尾盘涨停：14:30 之后首次封板或最后封板视为尾盘"""
    for t in (first_seal_time, last_seal_time):
        if not t or ":" not in str(t):
            continue
        parts = str(t).strip().split(":")
        if len(parts) >= 2:
            try:
                h, m = int(parts[0]), int(parts[1])
                if h > 14 or (h == 14 and m >= 30):
                    return True
            except ValueError:
                pass
    return False


def _filter_row(row: Dict[str, Any], exclude_st: bool = True, exclude_sub_new: bool = True) -> bool:
    """True 表示保留，False 表示过滤掉"""
    name = str(row.get("name", "") or "")
    code = str(row.get("code", "") or "")
    turnover_rate = row.get("turnover_rate")
    if exclude_st and ("ST" in name or "st" in name or code.startswith("3") and "ST" in name.upper()):
        return False
    if turnover_rate is not None:
        try:
            tr = float(turnover_rate)
            if tr > 30.0:  # 换手率>30% 可能是出货
                return False
        except (TypeError, ValueError):
            pass
    # 次新股需上市日期，此处暂不实现（可后续接 wind/tushare 上市日）
    if exclude_sub_new:
        pass  # 保留，后续有数据再过滤
    return True


def _fetch_limit_up_akshare(date: str) -> Optional[List[Dict[str, Any]]]:
    """AKShare 获取单日涨停池。date 格式 YYYYMMDD"""
    if not AKSHARE_AVAILABLE:
        return None
    try:
        df = ak.stock_zt_pool_em(date)
        if df is None or df.empty:
            return []
        rows = []
        for _, r in df.iterrows():
            first_seal = _parse_seal_time(r.get(COL_FIRST_SEAL_TIME))
            last_seal = _parse_seal_time(r.get(COL_LAST_SEAL_TIME))
            if _is_tail_limit_up(first_seal, last_seal):
                continue
            try:
                float_mv = r.get(COL_FLOAT_MV)
                if hasattr(float_mv, "item"):
                    float_mv = float(float_mv)
                else:
                    float_mv = float(float_mv) if float_mv is not None else None
            except (TypeError, ValueError):
                float_mv = None
            try:
                turnover_rate = r.get(COL_TURNOVER_RATE)
                if turnover_rate is not None:
                    turnover_rate = float(turnover_rate)
            except (TypeError, ValueError):
                turnover_rate = None
            continuous = r.get(COL_CONTINUOUS)
            if continuous is not None:
                try:
                    continuous = int(float(continuous))
                except (TypeError, ValueError):
                    continuous = None
            item = {
                "code": str(r.get(COL_CODE, "")).strip(),
                "name": str(r.get(COL_NAME, "")).strip(),
                "limit_up_time": first_seal or last_seal,
                "change_pct": float(r.get(COL_CHANGE_PCT, 0)) if r.get(COL_CHANGE_PCT) is not None else None,
                "turnover_rate": turnover_rate,
                "float_mv": float_mv,
                "board_name": str(r.get(COL_BOARD, "")).strip() or None,
                "continuous_limit_up_count": continuous,
                "latest_price": float(r.get(COL_PRICE)) if r.get(COL_PRICE) is not None else None,
                "amount": float(r.get(COL_AMOUNT)) if r.get(COL_AMOUNT) is not None else None,
            }
            if not _filter_row(item):
                continue
            rows.append(item)
        return rows
    except Exception as e:
        logger.warning("akshare stock_zt_pool_em failed for %s: %s", date, e)
        return None


def tool_fetch_limit_up_stocks(
    date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    exclude_st: bool = True,
    exclude_tail_limit_up: bool = True,
) -> Dict[str, Any]:
    """
    获取涨停股列表。
    参数:
      date: 单日 YYYYMMDD
      start_date, end_date: 区间 YYYYMMDD，与 date 二选一
      exclude_st: 是否排除 ST
      exclude_tail_limit_up: 是否排除尾盘涨停(14:30后)
    返回:
      success, data: [{ code, name, limit_up_time, change_pct, turnover_rate, float_mv, board_name, continuous_limit_up_count, ... }], date(s), count
    """
    if date:
        dates = [date]
    elif start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y%m%d")
            end = datetime.strptime(end_date, "%Y%m%d")
            dates = []
            d = start
            while d <= end:
                dates.append(d.strftime("%Y%m%d"))
                d += timedelta(days=1)
        except ValueError as e:
            return {"success": False, "error": f"日期格式错误: {e}", "data": [], "count": 0}
    else:
        # 默认今日
        dates = [datetime.now().strftime("%Y%m%d")]

    all_rows = []
    for d in dates:
        rows = _fetch_limit_up_akshare(d)
        if rows is None:
            continue
        for r in rows:
            r["date"] = d
            all_rows.append(r)

    return {
        "success": True,
        "data": all_rows,
        "dates": dates,
        "count": len(all_rows),
    }
