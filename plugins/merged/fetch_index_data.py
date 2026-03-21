"""
合并工具：指数数据采集
data_type: realtime | historical | minute | opening | global_spot
旧工具名作为别名时由 tool_runner 注入 data_type，此处统一入口。
"""

from typing import Dict, Any, Optional

# 延迟导入避免循环
def tool_fetch_index_data(
    data_type: str,
    index_code: Optional[str] = "000001",
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: Optional[int] = 5,
    mode: str = "production",
    **kwargs
) -> Dict[str, Any]:
    """
    获取指数数据（统一入口）。
    data_type: realtime | historical | minute | opening | global_spot
    """
    if data_type == "realtime":
        from data_collection.index.fetch_realtime import tool_fetch_index_realtime
        return tool_fetch_index_realtime(index_code=index_code or "000001", mode=mode)
    if data_type == "historical":
        from data_collection.index.fetch_historical import tool_fetch_index_historical
        return tool_fetch_index_historical(
            index_code=index_code or "000300",
            period=period or "daily",
            start_date=start_date,
            end_date=end_date
        )
    if data_type == "minute":
        from data_collection.index.fetch_minute import tool_fetch_index_minute
        return tool_fetch_index_minute(
            index_code=index_code or "000300",
            period=period or "5",
            lookback_days=lookback_days or 5,
            mode=mode
        )
    if data_type == "opening":
        from data_collection.index.fetch_opening import tool_fetch_index_opening
        return tool_fetch_index_opening(
            index_codes=kwargs.get("index_codes") or index_code,
            mode=mode,
        )
    if data_type == "global_spot":
        from data_collection.index.fetch_global import tool_fetch_global_index_spot
        return tool_fetch_global_index_spot(**kwargs)
    return {
        "success": False,
        "message": f"不支持的 data_type: {data_type}，应为 realtime | historical | minute | opening | global_spot",
        "data": None
    }
