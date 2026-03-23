"""
重试工具模块
提供网络请求重试机制

支持：
- 指数退避重试
- 可配置的重试次数和超时时间
- 可重试错误和不可重试错误的区分
"""

import time
import functools
from typing import Callable, Type, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class RetryConfig:
    """
    重试配置类
    """
    
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
        non_retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None
    ):
        """
        初始化重试配置
        
        Args:
            max_attempts: 最大重试次数（包括首次尝试）
            initial_delay: 初始延迟（秒）
            max_delay: 最大延迟（秒）
            exponential_base: 指数退避基数
            jitter: 是否添加随机抖动（避免惊群效应）
            retryable_exceptions: 可重试的异常类型
            non_retryable_exceptions: 不可重试的异常类型
        """
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions or (
            ConnectionError,
            TimeoutError,
            OSError,
            # requests库的异常
            Exception,  # 默认所有异常都可重试，除非在non_retryable中
        )
        self.non_retryable_exceptions = non_retryable_exceptions or (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        )


# 默认重试配置
DEFAULT_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    initial_delay=1.0,
    max_delay=60.0,
    exponential_base=2.0,
    jitter=True
)


def _calculate_delay(attempt: int, config: RetryConfig) -> float:
    """
    计算重试延迟（指数退避）
    
    Args:
        attempt: 当前尝试次数（从0开始）
        config: 重试配置
        
    Returns:
        延迟时间（秒）
    """
    # 指数退避：delay = initial_delay * (exponential_base ^ attempt)
    delay = config.initial_delay * (config.exponential_base ** attempt)
    
    # 限制最大延迟
    delay = min(delay, config.max_delay)
    
    # 添加随机抖动（±20%）
    if config.jitter:
        import random
        jitter_amount = delay * 0.2 * (random.random() * 2 - 1)  # -20% 到 +20%
        delay = max(0, delay + jitter_amount)
    
    return delay


def _is_retryable_exception(exception: Exception, config: RetryConfig) -> bool:
    """
    判断异常是否可重试
    
    Args:
        exception: 异常对象
        config: 重试配置
        
    Returns:
        是否可重试
    """
    # 检查是否在不可重试列表中
    if config.non_retryable_exceptions:
        for exc_type in config.non_retryable_exceptions:
            if isinstance(exception, exc_type):
                return False
    
    # 检查是否在可重试列表中
    if config.retryable_exceptions:
        for exc_type in config.retryable_exceptions:
            if isinstance(exception, exc_type):
                return True
    
    # 默认：如果不在不可重试列表中，且可重试列表包含Exception，则可重试
    if Exception in config.retryable_exceptions:
        return True
    
    return False


def retry_on_failure(
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None
) -> Callable:
    """
    重试装饰器
    
    使用示例：
        @retry_on_failure(config=RetryConfig(max_attempts=3))
        def fetch_data(url):
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
    
    Args:
        config: 重试配置，如果为None使用默认配置
        on_retry: 重试回调函数，接收(exception, attempt)参数
        
    Returns:
        装饰器函数
    """
    if config is None:
        config = DEFAULT_RETRY_CONFIG
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    # 执行函数
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    # 检查是否可重试
                    if not _is_retryable_exception(e, config):
                        logger.warning(
                            f"Non-retryable exception in {func.__name__}: {type(e).__name__}: {e}"
                        )
                        raise
                    
                    # 检查是否还有重试机会
                    if attempt < config.max_attempts - 1:
                        # 计算延迟
                        delay = _calculate_delay(attempt, config)
                        
                        # 记录重试信息
                        logger.warning(
                            f"Retrying {func.__name__} after {delay:.2f}s "
                            f"(attempt {attempt + 1}/{config.max_attempts}): {type(e).__name__}: {e}"
                        )
                        
                        # 调用重试回调
                        if on_retry:
                            try:
                                on_retry(e, attempt + 1)
                            except Exception as callback_error:
                                logger.error(f"Error in retry callback: {callback_error}")
                        
                        # 等待后重试
                        time.sleep(delay)
                    else:
                        # 最后一次尝试失败
                        logger.error(
                            f"Failed {func.__name__} after {config.max_attempts} attempts: "
                            f"{type(e).__name__}: {e}"
                        )
                        raise
            
            # 如果所有重试都失败，抛出最后一个异常
            if last_exception:
                raise last_exception
        
        return wrapper
    
    return decorator


# 便捷函数：为requests库的常见异常创建重试配置
def create_requests_retry_config(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0
) -> RetryConfig:
    """
    创建适用于requests库的重试配置
    
    Args:
        max_attempts: 最大重试次数
        initial_delay: 初始延迟（秒）
        max_delay: 最大延迟（秒）
        
    Returns:
        重试配置对象
    """
    try:
        import requests
        retryable_exceptions = (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            ConnectionError,
            TimeoutError,
            OSError,
        )
    except ImportError:
        # 如果requests未安装，使用通用异常
        retryable_exceptions = (
            ConnectionError,
            TimeoutError,
            OSError,
        )
    
    return RetryConfig(
        max_attempts=max_attempts,
        initial_delay=initial_delay,
        max_delay=max_delay,
        retryable_exceptions=retryable_exceptions,
        non_retryable_exceptions=(
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        )
    )
