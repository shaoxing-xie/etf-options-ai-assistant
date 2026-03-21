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
        from analysis.volatility_prediction import tool_predict_volatility
        result = tool_predict_volatility(
            underlying=underlying or symbol or "510300",
            contract_codes=contract_codes,
            **kwargs
        )
        # 工具层统一返回 dict，便于工作流/OpenClaw 解析；tool_predict_volatility 返回字符串
        if isinstance(result, dict):
            return result
        return {
            "success": True,
            "message": "波动率预测完成",
            "formatted_output": result if isinstance(result, str) else str(result),
            "data": None,
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
