"""
统一的日志配置模块
提供详细的日志记录功能，便于调试和错误追踪

日志结构：
- 按模块分类记录（模块名、函数名、行号）
- 详细的错误信息（包括堆栈跟踪）
- 按日期分割日志文件
- 支持不同日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
"""

import logging
import sys
import os
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional


class DetailedFormatter(logging.Formatter):
    """
    详细的日志格式化器
    包含：时间戳、日志级别、模块名、函数名、行号、消息、异常堆栈
    """
    
    def __init__(self):
        super().__init__(
            fmt='%(asctime)s | %(levelname)-8s | %(module)s.%(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    def formatException(self, ei):
        """
        格式化异常信息，包含完整的堆栈跟踪
        """
        import traceback
        return '\n'.join(traceback.format_exception(*ei))


def setup_logger(
    name: str,
    log_level: str = "INFO",
    log_dir: str = "logs",
    log_file_prefix: str = "option_trading",
    max_file_size_mb: int = 10,
    backup_count: int = 7,
    console_output: bool = True
) -> logging.Logger:
    """
    设置并返回一个配置好的日志记录器
    
    Args:
        name: 日志记录器名称（通常是模块名）
        log_level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        log_dir: 日志文件目录
        log_file_prefix: 日志文件前缀
        max_file_size_mb: 单个日志文件最大大小（MB）
        backup_count: 保留的日志文件数量
        console_output: 是否同时输出到控制台
    
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger(name)
    
    # 避免重复添加处理器
    if logger.handlers:
        return logger
    
    # 设置日志级别
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)
    
    # 检查是否禁用文件日志（用于回测等场景）
    disable_file_logging = os.environ.get('DISABLE_FILE_LOGGING', '0') == '1'
    
    # 文件处理器（带轮转）- 仅在未禁用时添加
    if not disable_file_logging:
        # 创建日志目录
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        # 日志文件路径（按日期命名）
        today = datetime.now().strftime("%Y%m%d")
        log_file = log_path / f"{log_file_prefix}_{today}.log"
        
        # 文件处理器（带轮转）
        max_bytes = max_file_size_mb * 1024 * 1024
        try:
            # 使用自定义的RotatingFileHandler，捕获轮转时的权限错误
            class SafeRotatingFileHandler(RotatingFileHandler):
                """安全的日志轮转处理器，捕获权限错误"""
                _rollover_warning_shown = False  # 类变量，只警告一次
                
                def doRollover(self):
                    try:
                        super().doRollover()
                        # 如果轮转成功，重置警告标志
                        SafeRotatingFileHandler._rollover_warning_shown = False
                    except (PermissionError, OSError) as e:
                        # 如果轮转失败，只警告一次，避免重复输出
                        if not SafeRotatingFileHandler._rollover_warning_shown:
                            sys.stderr.write(f"日志文件轮转失败（文件可能被占用）: {str(e)}\n")
                            sys.stderr.write("提示：请关闭占用日志文件的程序（如文本编辑器），后续将静默处理此错误\n")
                            SafeRotatingFileHandler._rollover_warning_shown = True
                        # 不抛出异常，继续使用当前日志文件
            
            file_handler = SafeRotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(DetailedFormatter())
            logger.addHandler(file_handler)
        except (PermissionError, OSError) as e:
            # 如果无法创建文件处理器（权限问题），只使用控制台输出
            # sys已在文件顶部导入，直接使用
            sys.stderr.write(f"无法创建日志文件处理器: {str(e)}，将只使用控制台输出\n")
    
    # 控制台处理器
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(DetailedFormatter())
        logger.addHandler(console_handler)
    
    return logger


# 日志配置缓存（避免重复加载配置）
_logger_config_cache = None


def get_module_logger(module_name: str) -> logging.Logger:
    """
    获取模块专用的日志记录器
    
    Args:
        module_name: 模块名称（通常是 __name__）
    
    Returns:
        logging.Logger: 日志记录器
    """
    global _logger_config_cache
    
    # 从配置加载日志设置（使用缓存避免重复加载）
    if _logger_config_cache is None:
        try:
            from src.config_loader import load_system_config
            
            config = load_system_config()
            logging_config = config.get('logging', {})
            
            log_level = logging_config.get('level', 'INFO')
            log_dir = logging_config.get('file_path', 'logs/option_trading_{date}.log')
            # 提取目录部分
            if '{date}' in log_dir:
                log_dir = log_dir.split('{date}')[0].rstrip('/')
            else:
                log_dir = 'logs'
            
            max_file_size_mb = logging_config.get('max_file_size_mb', 10)
            backup_count = logging_config.get('backup_count', 7)
            
            _logger_config_cache = {
                'log_level': log_level,
                'log_dir': log_dir,
                'max_file_size_mb': max_file_size_mb,
                'backup_count': backup_count
            }
            
        except Exception:
            # 如果配置加载失败，使用默认值
            _logger_config_cache = {
                'log_level': 'INFO',
                'log_dir': 'logs',
                'max_file_size_mb': 10,
                'backup_count': 7
            }
    
    return setup_logger(
        name=module_name,
        log_level=_logger_config_cache['log_level'],
        log_dir=_logger_config_cache['log_dir'],
        log_file_prefix='option_trading',
        max_file_size_mb=_logger_config_cache['max_file_size_mb'],
        backup_count=_logger_config_cache['backup_count'],
        console_output=True
    )


def log_error_with_context(
    logger: logging.Logger,
    error: Exception,
    context: dict,
    message: str = "发生错误"
):
    """
    记录带上下文的错误信息
    
    Args:
        logger: 日志记录器
        error: 异常对象
        context: 上下文信息字典
        message: 错误消息
    """
    context_str = ', '.join([f"{k}={v}" for k, v in context.items()])
    logger.error(
        f"{message} | 上下文: {context_str} | 错误类型: {type(error).__name__} | 错误信息: {str(error)}",
        exc_info=True
    )


def log_function_call(logger: logging.Logger, func_name: str, **kwargs):
    """
    记录函数调用信息（用于调试）
    
    Args:
        logger: 日志记录器
        func_name: 函数名
        **kwargs: 函数参数
    """
    params_str = ', '.join([f"{k}={v}" for k, v in kwargs.items()])
    logger.debug(f"调用函数: {func_name}({params_str})")


def log_function_result(logger: logging.Logger, func_name: str, result, duration: Optional[float] = None):
    """
    记录函数执行结果（用于调试）
    
    Args:
        logger: 日志记录器
        func_name: 函数名
        result: 函数返回值
        duration: 执行耗时（秒）
    """
    duration_str = f" | 耗时: {duration:.2f}秒" if duration else ""
    logger.debug(f"函数返回: {func_name}() -> {result}{duration_str}")
