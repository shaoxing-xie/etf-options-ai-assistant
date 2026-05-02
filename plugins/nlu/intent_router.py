from __future__ import annotations

from typing import Any, Dict, List, Optional

from plugins.analysis.six_index_next_day_predictor import predict_all
from plugins.analysis.technical_indicators import tool_calculate_technical_indicators
from src.features.six_index_features import build_feature_snapshot
from src.features.six_index_features import _call_data_plugin_tool as call_data_plugin_tool

INDEX_NAME_TO_CODE = {
    "上证": "000001.SH",
    "上证指数": "000001.SH",
    "沪深300": "000300.SH",
    "科创50": "000688.SH",
    "创业板": "399006.SZ",
    "创业板指": "399006.SZ",
    "中证500": "000905.SH",
    "中证1000": "000852.SH",
}


def _detect_intent(query: str) -> str:
    q = query.strip()
    if any(k in q for k in ("热点", "板块最热", "行业最热", "热度")):
        return "hotspot"
    if any(k in q for k in ("明天怎么看", "方向预测", "次日")):
        return "index_prediction"
    if any(k in q for k in ("技术分析", "K线", "均线", "macd", "rsi")):
        return "index_technical"
    if any(k in q for k in ("情绪", "北向", "资金面", "市场强弱")):
        return "market_sentiment"
    return "unknown"


def _extract_index_code(query: str) -> Optional[str]:
    for name, code in INDEX_NAME_TO_CODE.items():
        if name in query:
            return code
    return None


def _handle_hotspot() -> Dict[str, Any]:
    return call_data_plugin_tool("tool_hotspot_discovery", {"top_k": 5, "min_heat_score": 30})


def _handle_index_prediction(query: str) -> Dict[str, Any]:
    code = _extract_index_code(query)
    if not code:
        return {"success": False, "message": "未识别指数名称，请指定如：沪深300/科创50/中证1000"}
    doc = predict_all(build_feature_snapshot())
    predictions = [x for x in (doc.get("predictions") or []) if str(x.get("index_code") or "") == code]
    if not predictions:
        return {"success": False, "message": f"未找到指数 {code} 的预测结果"}
    return {"success": True, "prediction": predictions[0], "trade_date": doc.get("trade_date")}


def _handle_index_technical(query: str) -> Dict[str, Any]:
    code = _extract_index_code(query) or "000300.SH"
    symbol = code.split(".")[0]
    return tool_calculate_technical_indicators(
        symbol=symbol,
        data_type="index_daily",
        indicators=["rsi", "macd", "boll", "ma"],
        lookback_days=120,
    )


def _handle_market_sentiment() -> Dict[str, Any]:
    feature_doc = build_feature_snapshot()
    g = feature_doc.get("global_features") if isinstance(feature_doc.get("global_features"), dict) else {}
    return {
        "success": True,
        "trade_date": feature_doc.get("trade_date"),
        "sentiment_snapshot": {
            "northbound_intraday_score": g.get("northbound_intraday_score"),
            "market_main_force_score": g.get("market_main_force_score"),
            "limit_up_count": g.get("limit_up_count"),
            "top_hotspots": g.get("top_hotspots") or [],
            "hotspot_score": g.get("top_hotspot_score"),
        },
    }


def _unknown_example() -> List[str]:
    return [
        "今天什么板块最热",
        "沪深300明天怎么看",
        "科创50技术分析",
        "市场情绪怎么样",
    ]


def tool_nlu_query(query: str) -> Dict[str, Any]:
    user_query = str(query or "").strip()
    if not user_query:
        return {"success": False, "intent": "unknown", "message": "query 不能为空", "examples": _unknown_example()}

    intent = _detect_intent(user_query)
    if intent == "hotspot":
        result = _handle_hotspot()
    elif intent == "index_prediction":
        result = _handle_index_prediction(user_query)
    elif intent == "index_technical":
        result = _handle_index_technical(user_query)
    elif intent == "market_sentiment":
        result = _handle_market_sentiment()
    else:
        return {
            "success": False,
            "intent": "unknown",
            "message": "未识别意图，请使用示例问法。",
            "examples": _unknown_example(),
        }

    return {
        "success": bool(result.get("success", True)),
        "intent": intent,
        "query": user_query,
        "result": result,
    }

