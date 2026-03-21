"""
capital-flow 技能底层数据源：

- 封装 AkShare 个股资金流向接口（若可用）
- 对每只股票输出简单的主力/散户资金分析与风险标记

接口设计参考《涨停回马枪技能分析.md》 一.5 节：
- 输入：symbols, 可选 lookback_days
- 输出：flows: [{symbol, main_flow, retail_flow, big_order_ratio, limit_up_flow, flow_judgement, risk_flags}]
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import akshare as ak

    AKSHARE_AVAILABLE = True
except Exception:  # noqa: BLE001
    AKSHARE_AVAILABLE = False


def _normalize_symbols(symbols: Any) -> List[str]:
    if isinstance(symbols, str):
        raw = [s.strip() for s in symbols.replace(";", ",").split(",") if s.strip()]
    else:
        raw = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    # 简单去重
    seen = set()
    result: List[str] = []
    for s in raw:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _guess_fund_flow_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """
    针对 AkShare 个股资金流向常见字段名做一次模糊匹配，尽量在不同版本之间保持兼容。
    """
    cols = list(df.columns)

    def find_col(keywords: List[str]) -> Optional[str]:
        for c in cols:
            name = str(c)
            if any(k in name for k in keywords):
                return c
        return None

    return {
        "date": find_col(["日期", "trade_date", "date"]),
        "main_net": find_col(["主力净流入", "主力净额"]),
        "retail_net": find_col(["散户净流入", "小单净额"]),
        "big_order_ratio": find_col(["大单", "超大单"]),
        "amount": find_col(["成交额", "成交金额"]),
    }


def _fetch_single_symbol_flow(symbol: str, lookback_days: int) -> Dict[str, Any]:
    """
    获取单只个股资金流向，并做轻量汇总。
    在 AkShare 不可用或字段差异较大时，返回 degraded 结果，但保证结构稳定。
    """
    if not AKSHARE_AVAILABLE:
        return {
            "symbol": symbol,
            "success": False,
            "error": "AkShare 未安装，无法获取资金流向数据",
        }

    # 日期区间：最近 lookback_days 交易日（这里按自然日近似）
    end = datetime.now()
    start = end - timedelta(days=max(lookback_days, 1) * 2)

    df: Optional[pd.DataFrame] = None
    error_msg: Optional[str] = None

    # 1) 优先尝试 ak.stock_individual_fund_flow
    try:
        if hasattr(ak, "stock_individual_fund_flow"):
            df = ak.stock_individual_fund_flow(stock=symbol)  # type: ignore[arg-type]
    except TypeError:
        # 不同版本参数签名可能不同，尽量兼容但不抛出
        try:
            df = ak.stock_individual_fund_flow(symbol)  # type: ignore[call-arg]
        except Exception as e:  # noqa: BLE001
            error_msg = f"stock_individual_fund_flow 调用失败: {e}"
    except Exception as e:  # noqa: BLE001
        error_msg = f"stock_individual_fund_flow 异常: {e}"

    # 2) 备用：stock_fund_flow_individual
    if (df is None or df.empty) and hasattr(ak, "stock_fund_flow_individual"):
        try:
            alt_df = ak.stock_fund_flow_individual(symbol)  # type: ignore[call-arg]
            if alt_df is not None and not alt_df.empty:
                df = alt_df
                error_msg = None
        except Exception as e:  # noqa: BLE001
            if error_msg is None:
                error_msg = f"stock_fund_flow_individual 调用失败: {e}"

    if df is None or df.empty:
        return {
            "symbol": symbol,
            "success": False,
            "error": error_msg or "资金流向接口返回空数据",
        }

    cols = _guess_fund_flow_columns(df)
    date_col = cols["date"]
    if date_col:
        try:
            df = df.copy()
            df[date_col] = pd.to_datetime(df[date_col])
            df = df[(df[date_col] >= start) & (df[date_col] <= end)].copy()
            df = df.sort_values(date_col, ascending=True).tail(lookback_days)
        except Exception:
            # 日期解析失败时，仍保留 df，但不做截取
            pass

    # 计算今日/区间指标
    latest = df.iloc[-1] if not df.empty else None

    main_net_today = _safe_float(latest[cols["main_net"]]) if latest is not None and cols["main_net"] else 0.0
    retail_net_today = _safe_float(latest[cols["retail_net"]]) if latest is not None and cols["retail_net"] else 0.0
    big_order_ratio_today = (
        _safe_float(latest[cols["big_order_ratio"]]) if latest is not None and cols["big_order_ratio"] else 0.0
    )

    # 最近 N 日主力净流入合计 & 平均
    if cols["main_net"]:
        series_main = df[cols["main_net"]].apply(_safe_float)
        main_net_sum = float(series_main.sum())
        main_net_avg = float(series_main.mean())
    else:
        main_net_sum = 0.0
        main_net_avg = 0.0

    # 简单流向判断
    flow_judgement = "未知"
    risk_flags: List[str] = []

    if main_net_today > 0 and main_net_sum > 0:
        flow_judgement = "主力进场"
    elif main_net_today < 0 and main_net_sum < 0:
        flow_judgement = "主力出货"
        risk_flags.append("主力连续净流出")
    elif abs(main_net_today) < abs(main_net_avg) * 0.5:
        flow_judgement = "资金震荡"

    if big_order_ratio_today < -5:
        risk_flags.append("大单明显流出")
    elif big_order_ratio_today > 5:
        risk_flags.append("大单显著流入")

    return {
        "symbol": symbol,
        "success": True,
        "main_flow_today": round(main_net_today, 2),
        "retail_flow_today": round(retail_net_today, 2),
        "big_order_ratio_today": round(big_order_ratio_today, 2),
        "main_flow_sum": round(main_net_sum, 2),
        "main_flow_avg": round(main_net_avg, 2),
        "flow_judgement": flow_judgement,
        "risk_flags": risk_flags,
        "raw_available": bool(cols["main_net"]),
    }


def tool_capital_flow(
    symbols: Any,
    lookback_days: int = 3,
) -> Dict[str, Any]:
    """
    capital-flow 技能入口工具。

    Args:
        symbols: 股票列表，支持 ["600519", "000001"] 或 "600519,000001"。
        lookback_days: 资金流向回溯天数（近 N 日），默认 3。

    Returns:
        {
          "status": "success" | "error",
          "lookback_days": int,
          "flows": [
            {
              "symbol": "...",
              "main_flow_today": ...,
              "retail_flow_today": ...,
              "big_order_ratio_today": ...,
              "main_flow_sum": ...,
              "main_flow_avg": ...,
              "flow_judgement": "主力进场/主力出货/资金震荡/未知",
              "risk_flags": [...],
            },
            ...
          ],
        }
    """
    symbol_list = _normalize_symbols(symbols)
    if not symbol_list:
        return {"status": "error", "error": "symbols 不能为空", "flows": []}

    results: List[Dict[str, Any]] = []
    for s in symbol_list:
        try:
            item = _fetch_single_symbol_flow(s, lookback_days=lookback_days)
        except Exception as e:  # noqa: BLE001
            logger.error("获取 %s 资金流向失败: %s", s, e)
            item = {"symbol": s, "success": False, "error": str(e)}
        results.append(item)

    return {
        "status": "success",
        "lookback_days": lookback_days,
        "flows": results,
    }


if __name__ == "__main__":
    import json

    demo = tool_capital_flow(["600519", "000001"], lookback_days=3)
    print(json.dumps(demo, ensure_ascii=False, indent=2))

