"""
信号生成入口（原系统）
根据 underlying 拉取指数分钟数据与 ETF 当前价，调用 signal_generator.generate_signals。
供 OpenClaw tool_runner / 定时任务调用。
"""

from typing import Dict, Any, List
from datetime import datetime

from src.data_collector import (
    fetch_index_minute_data_with_fallback,
    get_etf_current_price,
)
from src.signal_generator import generate_signals
from src.config_loader import load_system_config
from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


def tool_generate_signals(
    underlying: str = "510300",
    mode: str = "production",
) -> Dict[str, Any]:
    """
    根据标的生成交易信号（原系统逻辑）。
    使用 src.data_collector 拉取 000300 指数分钟数据与 ETF 当前价，调用 src.signal_generator.generate_signals。
    """
    try:
        index_30m, index_15m = fetch_index_minute_data_with_fallback(
            lookback_days=5,
            max_retries=2,
            retry_delay=1.0,
        )
        if index_30m is None or index_30m.empty:
            return {
                "success": False,
                "message": "获取指数分钟数据失败或为空，无法生成信号",
                "data": None,
            }
        etf_price = get_etf_current_price(symbol=underlying)
        if etf_price is None or etf_price <= 0:
            return {
                "success": False,
                "message": f"获取ETF {underlying} 当前价失败或无效，无法生成信号",
                "data": None,
            }
        config = None
        try:
            config = load_system_config()
        except Exception as e:
            logger.debug(f"加载系统配置失败，使用默认/空 config: {e}", exc_info=True)
        signals = generate_signals(
            index_minute=index_30m,
            etf_current_price=etf_price,
            config=config,
        )
        if not signals or not isinstance(signals, list):
            return {
                "success": True,
                "message": "当前无新信号（去重或条件未触发）",
                "data": {
                    "signal_id": datetime.now().strftime("%Y%m%d%H%M%S"),
                    "signal_type": None,
                    "signal_strength": None,
                    "trend_strength": None,
                    "signal_confidence": None,
                    "signals": [],
                },
            }
        # 同一次可能同时产出 call/put；为了避免工作流条件只看第一条而漏掉另一方向，
        # 这里把返回的 signal_strength 提升为“全部信号中的最大强度”。
        strengths: List[float] = []
        for s in signals:
            if not isinstance(s, dict):
                continue
            v = s.get("signal_strength", None)
            try:
                if v is not None:
                    strengths.append(float(v))
            except (TypeError, ValueError):
                continue

        max_strength = max(strengths) if strengths else None

        max_signal = None
        if max_strength is not None:
            for s in signals:
                if isinstance(s, dict) and s.get("signal_strength", None) == max_strength:
                    max_signal = s
                    break

        # 代表信号如果拿不到，就退化使用第一条
        rep = max_signal if isinstance(max_signal, dict) else signals[0]

        # 同一次同时有 call/put：用更明确的类型标签，便于消息侧呈现
        signal_types = sorted(
            set(str(s.get("signal_type")) for s in signals if isinstance(s, dict) and s.get("signal_type"))
        )
        if len(signal_types) >= 2:
            signal_type_out = "both"
        else:
            signal_type_out = signal_types[0] if signal_types else None

        first = rep
        signal_id = (
            first.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            .replace("-", "")
            .replace(":", "")
            .replace(" ", "")[:14]
        )
        return {
            "success": True,
            "message": f"已生成 {len(signals)} 个信号",
            "data": {
                "signal_id": signal_id,
                "signal_type": signal_type_out,
                "signal_strength": max_strength if max_strength is not None else first.get("signal_strength"),
                "trend_strength": first.get("trend_strength", first.get("signal_strength")),
                "signal_confidence": first.get(
                    "signal_confidence",
                    max_strength if max_strength is not None else first.get("signal_strength"),
                ),
                "signals": signals,
            },
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"信号生成执行异常：{str(e)}",
            "data": None,
        }
