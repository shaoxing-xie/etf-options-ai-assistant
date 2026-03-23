"""
日志工具模块
集成原系统日志配置，为OpenClaw插件工具提供统一日志格式

支持：
- 统一日志格式（时间戳、级别、模块、函数、消息、上下文）
- 集成原系统日志配置
- 结构化日志支持（可选）
"""

import logging
import sys
import os
from typing import Optional, Dict, Any
from contextvars import ContextVar
import json

# 上下文变量（用于传递请求ID、工作流ID等）
_request_id: ContextVar[Optional[str]] = ContextVar('request_id', default=None)
_workflow_id: ContextVar[Optional[str]] = ContextVar('workflow_id', default=None)


def get_module_logger(module_name: str) -> logging.Logger:
    """
    获取模块专用的日志记录器（集成原系统日志配置）
    
    Args:
        module_name: 模块名称（通常是 __name__）
    
    Returns:
        logging.Logger: 日志记录器
    """
    try:
        from src.logger_config import get_module_logger as original_get_module_logger
        return original_get_module_logger(module_name)
    except ImportError:
        # 如果原系统不可用，使用默认配置
        return _setup_default_logger(module_name)


def _setup_default_logger(module_name: str) -> logging.Logger:
    """
    设置默认日志记录器（原系统不可用时使用）
    
    Args:
        module_name: 模块名称
    
    Returns:
        logging.Logger: 日志记录器
    """
    logger = logging.getLogger(module_name)
    
    # 避免重复添加处理器
    if logger.handlers:
        return logger
    
    # 设置日志级别
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    level = getattr(logging, log_level, logging.INFO)
    logger.setLevel(level)
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(_StandardFormatter())
    logger.addHandler(console_handler)
    
    return logger


class _StandardFormatter(logging.Formatter):
    """
    标准日志格式化器
    包含：时间戳、日志级别、模块名、函数名、行号、消息、上下文
    """
    
    def __init__(self):
        super().__init__(
            fmt='%(asctime)s | %(levelname)-8s | %(module)s.%(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录，添加上下文信息"""
        # 添加上下文信息
        context_parts = []
        
        request_id = _request_id.get()
        if request_id:
            context_parts.append(f"req_id={request_id}")
        
        workflow_id = _workflow_id.get()
        if workflow_id:
            context_parts.append(f"workflow_id={workflow_id}")
        
        if context_parts:
            record.msg = f"{record.msg} [{' '.join(context_parts)}]"
        
        return super().format(record)


def set_request_context(request_id: Optional[str] = None, workflow_id: Optional[str] = None):
    """
    设置请求上下文（用于日志追踪）
    
    Args:
        request_id: 请求ID
        workflow_id: 工作流ID
    """
    if request_id:
        _request_id.set(request_id)
    if workflow_id:
        _workflow_id.set(workflow_id)


def clear_request_context():
    """清除请求上下文"""
    _request_id.set(None)
    _workflow_id.set(None)


def log_tool_call(logger: logging.Logger, tool_name: str, params: Dict[str, Any], result: Optional[Dict[str, Any]] = None):
    """
    记录工具调用（INFO级别）
    
    Args:
        logger: 日志记录器
        tool_name: 工具名称
        params: 工具参数
        result: 工具结果（可选）
    """
    # 记录调用信息
    params_str = json.dumps(params, ensure_ascii=False, default=str)[:200]  # 限制长度
    logger.info(f"Tool call: {tool_name} | params: {params_str}")
    
    # 记录结果摘要（如果提供）
    if result:
        success = result.get('success', False)
        if success:
            logger.info(f"Tool result: {tool_name} | success=True")
        else:
            error_msg = result.get('message', result.get('error', 'Unknown error'))[:200]
            logger.warning(f"Tool result: {tool_name} | success=False | error: {error_msg}")


def log_tool_error(logger: logging.Logger, tool_name: str, error: Exception, params: Optional[Dict[str, Any]] = None):
    """
    记录工具错误（ERROR级别）
    
    Args:
        logger: 日志记录器
        tool_name: 工具名称
        error: 异常对象
        params: 工具参数（可选）
    """
    params_str = ""
    if params:
        params_str = f" | params: {json.dumps(params, ensure_ascii=False, default=str)[:200]}"
    
    logger.error(f"Tool error: {tool_name}{params_str} | {type(error).__name__}: {str(error)}", exc_info=True)
