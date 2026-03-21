"""
合并工具：期权数据采集
data_type: realtime | greeks | minute
"""

from typing import Dict, Any, Optional

def tool_fetch_option_data(
    data_type: str,
    contract_code: Optional[str] = None,
    period: Optional[str] = "15",
    **kwargs
) -> Dict[str, Any]:
    """
    获取期权数据（统一入口）。
    data_type: realtime | greeks | minute
    """
    if not contract_code:
        return {"success": False, "message": "缺少 contract_code", "data": None}
    if data_type == "realtime":
        from data_collection.option.fetch_realtime import tool_fetch_option_realtime
        return tool_fetch_option_realtime(contract_code=contract_code, **kwargs)
    if data_type == "greeks":
        from data_collection.option.fetch_greeks import tool_fetch_option_greeks
        return tool_fetch_option_greeks(contract_code=contract_code, **kwargs)
    if data_type == "minute":
        from data_collection.option.fetch_minute import tool_fetch_option_minute
        return tool_fetch_option_minute(contract_code=contract_code, period=period or "15", **kwargs)
    return {
        "success": False,
        "message": f"不支持的 data_type: {data_type}，应为 realtime | greeks | minute",
        "data": None
    }
