"""
波动率预测引擎模块
用于IV百分位调整和GARCH-IV预测（阶段2）
GK优化：增加指数GARCH区间预测
"""

from .iv_percentile_adjuster import IVPercentileAdjuster
from typing import Any

# 先把可选引擎/预测器声明为 Any，避免 ImportError 分支把“类型”重新赋值为 None 时触发 mypy 的 misc/assignment 报错
GARCHIVPredictor: Any = None
BlackScholesPricer: Any = None
GARCHIVEngine: Any = None
ARCH_AVAILABLE: bool = False

IndexGARCHPredictor: Any = None
INDEX_GARCH_AVAILABLE: bool = False

# 阶段2：GARCH-IV引擎（可选）
try:
    from .garch_model import GARCHIVPredictor, ARCH_AVAILABLE
    from .option_pricer import BlackScholesPricer
    from .garch_iv_engine import GARCHIVEngine
    GARCH_AVAILABLE = True
except ImportError:
    GARCH_AVAILABLE = False

# GK优化：指数GARCH预测器（可选）
try:
    from .index_garch_predictor import IndexGARCHPredictor
    INDEX_GARCH_AVAILABLE = True
except ImportError:
    INDEX_GARCH_AVAILABLE = False

__all__ = [
    'IVPercentileAdjuster',
    'GARCHIVPredictor',
    'BlackScholesPricer',
    'GARCHIVEngine',
    'IndexGARCHPredictor',
    'GARCH_AVAILABLE',
    'ARCH_AVAILABLE',
    'INDEX_GARCH_AVAILABLE'
]
