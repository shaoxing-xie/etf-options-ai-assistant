"""
dragon-tiger-list 技能底层数据源：
- 结合当日涨停池（tool_fetch_limit_up_stocks）
- 接入龙虎榜明细（AkShare stock_lhb_detail_em）

输出结构尽量对齐 《涨停回马枪技能分析.md》 一.5 节中的约定：
- limit_up_list: 涨停股基础信息
- lhb_summary: 每只个股在龙虎榜上的资金汇总
- yoozi_profiles: 简单的游资席位画像（可后续接本地席位库增强）
- reason_tags: 上榜原因标签（规则化）
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import akshare as ak

    AKSHARE_AVAILABLE = True
except Exception:  # noqa: BLE001
    AKSHARE_AVAILABLE = False


def _normalize_date_yyyymmdd(date: Optional[str]) -> str:
    """将多种日期格式归一为 YYYYMMDD，默认返回今天。"""
    if not date:
        return datetime.now().strftime("%Y%m%d")
    s = str(date).strip()
    # 2024-03-08 -> 20240308
    if len(s) == 10 and s.count("-") == 2:
        return s.replace("-", "")
    if len(s) == 8 and s.isdigit():
        return s
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.strftime("%Y%m%d")
    except Exception:
        try:
            dt = datetime.strptime(s, "%Y%m%d")
            return dt.strftime("%Y%m%d")
        except Exception:
            return datetime.now().strftime("%Y%m%d")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _extract_lhb_core_columns(df) -> Tuple[str, str, str, str]:
    """
    根据常见的 AkShare 龙虎榜列名，推断关键字段。

    返回：(代码列名, 名称列名, 上榜原因列名, 净买额列名)
    若未找到对应列，则尽量退化但不报错。
    """
    cols = list(df.columns)
    code_col = next((c for c in cols if c in ("代码", "证券代码", "stock_code")), cols[0])
    name_col = next((c for c in cols if c in ("名称", "证券简称", "stock_name")), cols[1] if len(cols) > 1 else cols[0])
    reason_col = next((c for c in cols if "原因" in str(c)), "")
    # AkShare 通常类似 “净买额-万” / “净买额(万)” / “净买额”
    net_cols = [c for c in cols if "净买额" in str(c)]
    net_col = net_cols[0] if net_cols else ""
    return code_col, name_col, reason_col, net_col


def _build_reason_tags(reason: Optional[str]) -> List[str]:
    """将上榜原因字符串拆分为若干标签（非常轻量的规则，后续可接 NLP）。"""
    if not reason:
        return []
    text = str(reason).strip().replace("；", ";").replace("|", ";").replace("、", ";")
    parts = [p.strip() for p in text.split(";") if p.strip()]
    # 粗略规整：去重 + 保留原文
    seen = set()
    tags: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            tags.append(p)
    return tags


def _build_yoozi_profiles_for_symbol(seat_names: List[str]) -> Dict[str, Any]:
    """
    游资席位“画像”占位实现：
    - 目前仅返回席位名称列表，方便后续接入本地游资席位库（JSON / YAML）做标签增强。
    """
    unique_seats = sorted({s for s in seat_names if s})
    return {
        "seat_count": len(unique_seats),
        "seats": unique_seats,
        # 预留字段：后续可填充 {seat_name: ["章盟主", "超短"]} 等风格标签
        "seat_tags": {},
    }


def _fetch_lhb_akshare(date_yyyymmdd: str):
    """
    使用 AkShare 获取指定日期的龙虎榜明细。
    AkShare 典型接口：stock_lhb_detail_em(date="20231129")
    """
    if not AKSHARE_AVAILABLE:
        logger.warning("AkShare 未安装，无法获取龙虎榜数据")
        return None
    try:
        df = ak.stock_lhb_detail_em(date_yyyymmdd)
    except Exception as e:  # noqa: BLE001
        logger.warning("akshare.stock_lhb_detail_em 调用失败 %s: %s", date_yyyymmdd, e)
        return None
    if df is None or df.empty:
        return None
    return df


def tool_dragon_tiger_list(date: Optional[str] = None) -> Dict[str, Any]:
    """
    dragon-tiger-list 技能主入口（Python 工具层）。

    Args:
        date: 交易日期，支持 YYYYMMDD / YYYY-MM-DD，不传则默认今天。

    Returns:
        {
          "status": "success" | "error",
          "date": "YYYYMMDD",
          "limit_up_list": [...],   # 直接复用 tool_fetch_limit_up_stocks 的结构
          "lhb_summary": [...],     # 每只个股在龙虎榜上的资金与原因汇总
          "yoozi_profiles": {...},  # code -> { seat_count, seats, seat_tags }
          "reason_tags": {...},     # code -> [tags...]
          "warnings": [...],        # 例如 "龙虎榜数据缺失，仅返回涨停池"
        }
    """
    from plugins.data_collection.limit_up.fetch_limit_up import (  # type: ignore[import]
        tool_fetch_limit_up_stocks,
    )

    target_date = _normalize_date_yyyymmdd(date)
    warnings: List[str] = []

    # 1) 涨停池（已实现模块）
    limit_up_result = tool_fetch_limit_up_stocks(date=target_date)
    if not isinstance(limit_up_result, dict) or not limit_up_result.get("success"):
        warnings.append("涨停池获取失败，limit_up_list 为空")
        limit_up_list: List[Dict[str, Any]] = []
    else:
        # 仅保留当日记录
        raw_list = limit_up_result.get("data") or []
        limit_up_list = [r for r in raw_list if str(r.get("date")) == target_date]

    # 2) 龙虎榜明细
    lhb_df = _fetch_lhb_akshare(target_date)
    if lhb_df is None:
        warnings.append("龙虎榜数据源不可用或返回为空，lhb_summary 为空")
        return {
            "status": "success",
            "date": target_date,
            "limit_up_list": limit_up_list,
            "lhb_summary": [],
            "yoozi_profiles": {},
            "reason_tags": {},
            "warnings": warnings,
        }

    code_col, name_col, reason_col, net_col = _extract_lhb_core_columns(lhb_df)
    # 营业部/席位列（若存在）
    seat_col_candidates = [c for c in lhb_df.columns if "营业部" in str(c) or "席位" in str(c)]
    seat_col = seat_col_candidates[0] if seat_col_candidates else ""

    # 3) 逐股汇总龙虎榜数据
    grouped = {}
    for _, row in lhb_df.iterrows():
        code = str(row.get(code_col, "")).strip()
        if not code:
            continue
        info = grouped.setdefault(
            code,
            {
                "code": code,
                "name": str(row.get(name_col, "")).strip(),
                "net_amount": 0.0,
                "buy_amount": 0.0,
                "sell_amount": 0.0,
                "reasons": [],
                "seat_names": [],
                "row_count": 0,
            },
        )
        # 净买额（万）
        if net_col:
            info["net_amount"] += _safe_float(row.get(net_col))
        # 买入/卖出金额字段（若存在）
        buy_cols = [c for c in lhb_df.columns if "买入金额" in str(c)]
        sell_cols = [c for c in lhb_df.columns if "卖出金额" in str(c)]
        if buy_cols:
            info["buy_amount"] += _safe_float(row.get(buy_cols[0]))
        if sell_cols:
            info["sell_amount"] += _safe_float(row.get(sell_cols[0]))
        if reason_col:
            r_text = str(row.get(reason_col, "")).strip()
            if r_text:
                info["reasons"].append(r_text)
        if seat_col:
            seat_name = str(row.get(seat_col, "")).strip()
            if seat_name:
                info["seat_names"].append(seat_name)
        info["row_count"] += 1

    # 4) 构造输出结构
    lhb_summary: List[Dict[str, Any]] = []
    yoozi_profiles: Dict[str, Any] = {}
    reason_tags: Dict[str, List[str]] = {}

    for code, agg in grouped.items():
        reasons = agg.get("reasons") or []
        # 统一 reason 文本并生成 tags
        if reasons:
            merged_reason = ";".join(sorted(set(reasons)))
        else:
            merged_reason = ""
        tags = _build_reason_tags(merged_reason)

        lhb_summary.append(
            {
                "code": code,
                "name": agg.get("name"),
                "net_amount": round(float(agg.get("net_amount", 0.0)), 2),
                "buy_amount": round(float(agg.get("buy_amount", 0.0)), 2),
                "sell_amount": round(float(agg.get("sell_amount", 0.0)), 2),
                "row_count": int(agg.get("row_count", 0)),
                "reason": merged_reason,
                "reason_tags": tags,
            }
        )
        yoozi_profiles[code] = _build_yoozi_profiles_for_symbol(agg.get("seat_names") or [])
        reason_tags[code] = tags

    # 5) 将 limit_up_list 与 lhb_summary 对齐（便于下游按 code join）
    codes_in_lhb = {item["code"] for item in lhb_summary}
    for item in limit_up_list:
        code = str(item.get("code", "")).strip()
        item["in_lhb"] = code in codes_in_lhb

    return {
        "status": "success",
        "date": target_date,
        "limit_up_list": limit_up_list,
        "lhb_summary": lhb_summary,
        "yoozi_profiles": yoozi_profiles,
        "reason_tags": reason_tags,
        "warnings": warnings,
    }


if __name__ == "__main__":
    # 简单本地测试（不会在 OpenClaw 中调用）
    import json

    result = tool_dragon_tiger_list()
    print(json.dumps(result, ensure_ascii=False, indent=2))

