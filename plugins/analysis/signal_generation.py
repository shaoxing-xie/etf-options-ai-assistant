"""
信号生成插件（兼容层）
优先使用原系统 src.signal_generation.tool_generate_signals，仅当 src 不可用时回退到本地实现。
TOOL_MAP 已指向 src.signal_generation，此处供工作流/测试中「from analysis.signal_generation import tool_generate_signals」兼容。
"""

from typing import Dict, Any

try:
    from src.signal_generation import tool_generate_signals as _tool_generate_signals
    _USE_SRC = True
except ImportError:
    _USE_SRC = False
    _tool_generate_signals = None


def tool_generate_signals(
    underlying: str = "510300",
    mode: str = "production",
) -> Dict[str, Any]:
    if _USE_SRC and _tool_generate_signals is not None:
        return _tool_generate_signals(underlying=underlying, mode=mode)
    # 回退：返回明确错误，提示依赖 src
    return {
        "success": False,
        "message": "信号生成依赖原系统 src.signal_generation，请确保项目根在 Python 路径中并可使用 src 模块",
        "data": None,
    }
