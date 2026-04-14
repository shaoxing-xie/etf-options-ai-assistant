"""
合并工具：ETF 数据采集
data_type: realtime | historical | minute
定时采集标的清单见合并后配置 `data_cache.etf_codes`（来源：`config/domains/reference.yaml`；另见 scripts/run_data_cache_collection.py）。
"""

from typing import Dict, Any, Optional

def tool_fetch_etf_data(
    data_type: str,
    etf_code: Optional[str] = "510300",
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: Optional[int] = 5,
    **kwargs
) -> Dict[str, Any]:
    """
    获取 ETF 数据（统一入口）。
    data_type: realtime | historical | minute
    """
    if data_type == "realtime":
        from plugins.data_collection.etf.fetch_realtime import tool_fetch_etf_realtime
        return tool_fetch_etf_realtime(etf_code=etf_code or "510300", **kwargs)
    if data_type == "historical":
        from plugins.data_collection.etf.fetch_historical import tool_fetch_etf_historical
        return tool_fetch_etf_historical(
            etf_code=etf_code or "510300",
            period=period or "daily",
            start_date=start_date,
            end_date=end_date
        )
    if data_type == "minute":
        from plugins.data_collection.etf.fetch_minute import tool_fetch_etf_minute
        return tool_fetch_etf_minute(
            etf_code=etf_code or "510300",
            period=period or "5",
            lookback_days=lookback_days or 5
        )
    return {
        "success": False,
        "message": f"不支持的 data_type: {data_type}，应为 realtime | historical | minute",
        "data": None
    }
