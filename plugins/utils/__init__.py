"""
OpenClaw插件工具类
提供缓存、重试、日志、性能监控等通用功能
"""

from .cache import cache_result, clear_cache, get_cache_stats
from .retry import retry_on_failure, RetryConfig
from .logging_utils import get_module_logger, set_request_context, clear_request_context, log_tool_call, log_tool_error
from .performance_monitor import (
    measure_execution_time,
    get_execution_stats,
    get_slow_tools,
    clear_execution_stats,
    get_resource_monitor,
    SLOW_TOOL_THRESHOLD
)

__all__ = [
    # 缓存
    'cache_result',
    'clear_cache',
    'get_cache_stats',
    # 重试
    'retry_on_failure',
    'RetryConfig',
    # 日志
    'get_module_logger',
    'set_request_context',
    'clear_request_context',
    'log_tool_call',
    'log_tool_error',
    # 性能监控
    'measure_execution_time',
    'get_execution_stats',
    'get_slow_tools',
    'clear_execution_stats',
    'get_resource_monitor',
    'SLOW_TOOL_THRESHOLD',
]
