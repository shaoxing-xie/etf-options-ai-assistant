"""
A50 期货与沪深300 现货涨跌幅缺口（可解释、非投资建议）。
编排现有采集工具，不重造行情源。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _last_two_closes_historical(index_code: str = "000300"):
    try:
        from merged.fetch_index_data import tool_fetch_index_data

        r = tool_fetch_index_data(
            data_type="historical",
            index_code=index_code,
            lookback_days=8,
        )
        if not isinstance(r, dict) or not r.get("success"):
            return None, None
        data = r.get("data")
        klines: List[Dict[str, Any]] = []
        if isinstance(data, dict) and isinstance(data.get("klines"), list):
            klines = [x for x in data["klines"] if isinstance(x, dict)]
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            block = data[0]
            if isinstance(block.get("klines"), list):
                klines = [x for x in block["klines"] if isinstance(x, dict)]
        if len(klines) < 2:
            return None, None
        try:
            c0 = float(klines[-1].get("close"))
            c1 = float(klines[-2].get("close"))
            return c0, c1
        except (TypeError, ValueError):
            return None, None
    except Exception:
        return None, None


def tool_overnight_calibration(
    hs300_last_close: Optional[float] = None,
    hs300_prev_close: Optional[float] = None,
) -> Dict[str, Any]:
    """
    比较 A50 主力（涨跌幅%）与沪深300 最近一日涨跌幅%，得到缺口与粗 impact_score。

    Args:
        hs300_last_close: 可选，若缺省则从指数日线取最后两日收盘推算。
        hs300_prev_close: 可选，与上一参数成对使用。
    """
    from plugins.data_collection.futures.fetch_a50 import tool_fetch_a50_data

    a50_res = tool_fetch_a50_data(data_type="realtime", use_cache=True)
    a50_chg: Optional[float] = None
    a50_price: Optional[float] = None
    if isinstance(a50_res, dict):
        spot = a50_res.get("spot_data")
        if isinstance(spot, dict):
            try:
                if spot.get("change_pct") is not None:
                    a50_chg = float(spot["change_pct"])
            except (TypeError, ValueError):
                pass
            try:
                if spot.get("current_price") is not None:
                    a50_price = float(spot["current_price"])
            except (TypeError, ValueError):
                pass

    lc = hs300_last_close
    pc = hs300_prev_close
    if lc is None or pc is None:
        last_c, prev_c = _last_two_closes_historical("000300")
        if lc is None:
            lc = last_c
        if pc is None:
            pc = prev_c

    hs300_chg: Optional[float] = None
    if lc is not None and pc is not None and pc != 0:
        try:
            hs300_chg = (float(lc) - float(pc)) / float(pc) * 100.0
        except (TypeError, ValueError):
            hs300_chg = None

    gap: Optional[float] = None
    if a50_chg is not None and hs300_chg is not None:
        gap = round(a50_chg - hs300_chg, 4)

    impact_score: Optional[float] = None
    if gap is not None:
        raw = gap / 3.0
        impact_score = round(max(-1.0, min(1.0, raw)), 4)

    return {
        "success": True,
        "message": "ok",
        "data": {
            "a50_change_pct": a50_chg,
            "a50_last_price": a50_price,
            "hs300_last_close": lc,
            "hs300_prev_close": pc,
            "hs300_daily_change_pct": round(hs300_chg, 4) if hs300_chg is not None else None,
            "a50_vs_hs300_gap_pct": gap,
            "impact_score": impact_score,
            "numeric_unverified": False,
            "note": "impact_score=clamp((A50%-沪深300日涨跌幅%)/3,-1,1)；的点价口径以各工具为准",
            "a50_tool_message": a50_res.get("message") if isinstance(a50_res, dict) else None,
        },
    }
