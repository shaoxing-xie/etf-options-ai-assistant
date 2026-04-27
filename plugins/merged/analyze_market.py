"""
合并工具：时段市场分析
moment: after_close | before_open | opening
"""

from typing import Dict, Any

def tool_analyze_market(moment: str, **kwargs) -> Dict[str, Any]:
    """
    执行市场分析（按时段）。
    moment: after_close | before_open | opening
    """
    if moment == "after_close":
        from plugins.analysis.trend_analysis import tool_analyze_after_close
        return tool_analyze_after_close(**kwargs)
    if moment == "before_open":
        from plugins.analysis.trend_analysis import tool_analyze_before_open
        return tool_analyze_before_open(**kwargs)
    if moment == "opening":
        from plugins.analysis.trend_analysis import tool_analyze_opening_market
        return tool_analyze_opening_market(**kwargs)
    return {
        "success": False,
        "message": f"不支持的 moment: {moment}，应为 after_close | before_open | opening",
        "data": None
    }
