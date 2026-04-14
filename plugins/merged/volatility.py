"""
合并工具：波动率
mode: predict | historical
"""

from typing import Dict, Any, Optional

def tool_volatility(
    mode: str,
    underlying: Optional[str] = "510300",
    symbol: Optional[str] = None,
    contract_codes: Optional[list] = None,
    data_type: Optional[str] = None,
    lookback_days: Optional[int] = 30,
    **kwargs
) -> Dict[str, Any]:
    """
    波动率预测或历史波动率（统一入口）。
    mode: predict | historical
    """
    if mode == "predict":
        # 使用 volatility_prediction 保留结构化 data；勿仅用 tool_predict_volatility 的纯字符串，
        # 否则 send_daily_report / 开盘复合工具只能塞 Markdown，导致章节八嵌套 ## 与版式错乱。
        from plugins.analysis.volatility_prediction import volatility_prediction

        und = underlying or symbol or "510300"
        full = volatility_prediction(
            underlying=und,
            contract_codes=contract_codes,
            asset_type_hint=kwargs.get("asset_type_hint"),
        )
        if not isinstance(full, dict):
            return {
                "success": False,
                "message": "波动率预测返回异常",
                "formatted_output": str(full),
                "data": None,
            }
        return {
            "success": bool(full.get("success")),
            "message": full.get("message") or "波动率预测完成",
            "formatted_output": full.get("formatted_output"),
            "data": full.get("data"),
            "all_results": full.get("all_results"),
            "llm_enhanced": full.get("llm_enhanced"),
        }
    if mode == "historical":
        from analysis.historical_volatility import tool_calculate_historical_volatility
        return tool_calculate_historical_volatility(
            symbol=symbol or underlying or "510300",
            data_type=data_type,
            lookback_days=lookback_days or 30,
            **kwargs
        )
    return {
        "success": False,
        "message": f"不支持的 mode: {mode}，应为 predict | historical",
        "data": None
    }
