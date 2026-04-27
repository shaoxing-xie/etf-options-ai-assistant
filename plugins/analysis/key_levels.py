"""
指数关键位（支撑/压力）简算：MA20、近窗高低、整数关口。
供盘前晨报展示，非投资建议。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def tool_compute_index_key_levels(
    index_code: str = "000300",
    lookback_days: int = 120,
    max_gap_pct: float = 0.035,
) -> Dict[str, Any]:
    """
    基于最近日线计算 2～3 个支撑位与压力位。
    """
    try:
        from datetime import datetime, timedelta

        import pytz

        today = datetime.now(pytz.timezone("Asia/Shanghai")).strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=int(lookback_days))).strftime("%Y%m%d")

        from src.data_collector import fetch_index_daily_em

        df = fetch_index_daily_em(
            symbol=index_code,
            period="daily",
            start_date=start,
            end_date=today,
        )
        if df is None or df.empty:
            return {
                "success": False,
                "message": "no_data",
                "data": None,
            }
        close_col = "收盘" if "收盘" in df.columns else None
        if close_col is None:
            return {"success": False, "message": "no_close_col", "data": None}

        closes = df[close_col].astype(float)
        last = float(closes.iloc[-1])
        ma20 = float(closes.tail(20).mean()) if len(closes) >= 20 else last
        win = closes.tail(60) if len(closes) >= 60 else closes
        recent_low = float(win.min())
        recent_high = float(win.max())

        # 整数关口：当前价向下/向上取整百（指数点）
        floor100 = (int(last) // 100) * 100
        ceil100 = ((int(last) + 99) // 100) * 100

        def _gap_ok(x: float) -> bool:
            if last <= 0:
                return True
            return abs(x - last) / last <= max(0.0, float(max_gap_pct))

        support_candidates = [x for x in (ma20, floor100, recent_low) if x < last - 1e-6]
        resistance_candidates = [x for x in (ma20, ceil100, recent_high) if x > last + 1e-6]

        # 先取距离昨收最近、且偏离不过大的位；避免输出远离当前价的历史极值（如 4418）
        support_near = sorted(
            [x for x in support_candidates if _gap_ok(x)],
            key=lambda x: abs(last - x),
        )
        resistance_near = sorted(
            [x for x in resistance_candidates if _gap_ok(x)],
            key=lambda x: abs(x - last),
        )
        # 若附近无可用位，保留一个最近位，避免整段空白。
        if not support_near and support_candidates:
            support_near = [min(support_candidates, key=lambda x: abs(last - x))]
        if not resistance_near and resistance_candidates:
            resistance_near = [min(resistance_candidates, key=lambda x: abs(last - x))]

        supports = [round(x, 2) for x in support_near[:3]]
        resistances = [round(x, 2) for x in resistance_near[:3]]

        return {
            "success": True,
            "message": "ok",
            "data": {
                "index_code": index_code,
                "last_close": round(last, 4),
                "support": supports[:3],
                "resistance": resistances[:3],
                "note": "基于日线近似关键位，非精确交易价位",
                "max_gap_pct": round(max(0.0, float(max_gap_pct)), 4),
            },
        }
    except Exception as e:
        return {"success": False, "message": str(e), "data": None}
