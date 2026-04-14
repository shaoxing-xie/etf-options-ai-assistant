"""
信号生成插件（兼容层）
优先使用原系统 src.signal_generation，仅当 src 不可用时回退到明确错误。
"""

from typing import Any, Dict

try:
    from src.signal_generation import (
        tool_generate_option_trading_signals as _tool_generate_option_trading_signals,
        tool_generate_signals as _tool_generate_signals,
    )

    _USE_SRC = True
except ImportError:
    _USE_SRC = False
    _tool_generate_signals = None
    _tool_generate_option_trading_signals = None


def tool_generate_option_trading_signals(
    underlying: str = "510300",
    mode: str = "production",
) -> Dict[str, Any]:
    if _USE_SRC and _tool_generate_option_trading_signals is not None:
        return _tool_generate_option_trading_signals(underlying=underlying, mode=mode)
    return {
        "success": False,
        "message": "信号生成依赖原系统 src.signal_generation，请确保项目根在 Python 路径中并可使用 src 模块",
        "data": None,
    }


def tool_generate_signals(
    underlying: str = "510300",
    mode: str = "production",
) -> Dict[str, Any]:
    """兼容别名，等价于 tool_generate_option_trading_signals。"""
    if _USE_SRC and _tool_generate_signals is not None:
        return _tool_generate_signals(underlying=underlying, mode=mode)
    return {
        "success": False,
        "message": "信号生成依赖原系统 src.signal_generation，请确保项目根在 Python 路径中并可使用 src 模块",
        "data": None,
    }
