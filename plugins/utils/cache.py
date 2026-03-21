"""
缓存工具模块
提供内存缓存和计算结果缓存功能

支持：
- LRU缓存（最近最少使用）
- TTL缓存（基于时间过期）
- 缓存统计和监控
"""

import functools
import hashlib
import json
import time
from typing import Any, Callable, Dict, Optional, Tuple
from collections import OrderedDict
import threading


class LRUCache:
    """
    LRU缓存实现（线程安全）
    """
    
    def __init__(self, maxsize: int = 128):
        """
        初始化LRU缓存
        
        Args:
            maxsize: 最大缓存条目数
        """
        self.maxsize = maxsize
        self.cache: OrderedDict = OrderedDict()
        self.lock = threading.RLock()
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，如果不存在返回None
        """
        with self.lock:
            if key in self.cache:
                # 移动到末尾（最近使用）
                self.cache.move_to_end(key)
                self.hits += 1
                return self.cache[key][0]  # 返回 (value, timestamp) 中的 value
            else:
                self.misses += 1
                return None
    
    def set(self, key: str, value: Any) -> None:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
        """
        with self.lock:
            if key in self.cache:
                # 更新现有值
                self.cache.move_to_end(key)
                self.cache[key] = (value, time.time())
            else:
                # 添加新值
                if len(self.cache) >= self.maxsize:
                    # 删除最旧的项（第一个）
                    self.cache.popitem(last=False)
                self.cache[key] = (value, time.time())
    
    def clear(self) -> None:
        """清空缓存"""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            包含命中率、大小等统计信息的字典
        """
        with self.lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total * 100) if total > 0 else 0.0
            return {
                'size': len(self.cache),
                'maxsize': self.maxsize,
                'hits': self.hits,
                'misses': self.misses,
                'hit_rate': round(hit_rate, 2),
                'total_requests': total
            }


class TTLCache:
    """
    TTL缓存实现（基于时间过期，线程安全）
    """
    
    def __init__(self, default_ttl: int = 300):
        """
        初始化TTL缓存
        
        Args:
            default_ttl: 默认TTL（秒），默认5分钟
        """
        self.default_ttl = default_ttl
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.lock = threading.RLock()
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值（自动检查过期）
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，如果不存在或已过期返回None
        """
        with self.lock:
            if key in self.cache:
                value, expire_time = self.cache[key]
                if time.time() < expire_time:
                    # 未过期
                    self.hits += 1
                    return value
                else:
                    # 已过期，删除
                    del self.cache[key]
                    self.misses += 1
                    return None
            else:
                self.misses += 1
                return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: TTL（秒），如果为None使用默认TTL
        """
        with self.lock:
            ttl = ttl or self.default_ttl
            expire_time = time.time() + ttl
            self.cache[key] = (value, expire_time)
    
    def clear(self) -> None:
        """清空缓存"""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0
    
    def cleanup_expired(self) -> int:
        """
        清理过期条目
        
        Returns:
            清理的条目数
        """
        with self.lock:
            current_time = time.time()
            expired_keys = [
                key for key, (_, expire_time) in self.cache.items()
                if current_time >= expire_time
            ]
            for key in expired_keys:
                del self.cache[key]
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            包含命中率、大小等统计信息的字典
        """
        with self.lock:
            # 先清理过期条目
            self.cleanup_expired()
            total = self.hits + self.misses
            hit_rate = (self.hits / total * 100) if total > 0 else 0.0
            return {
                'size': len(self.cache),
                'default_ttl': self.default_ttl,
                'hits': self.hits,
                'misses': self.misses,
                'hit_rate': round(hit_rate, 2),
                'total_requests': total
            }


# 全局缓存实例
_memory_cache = LRUCache(maxsize=256)  # 内存缓存（数据访问）
_result_cache = TTLCache(default_ttl=300)  # 结果缓存（计算结果，默认5分钟）


def _generate_cache_key(func_name: str, *args, **kwargs) -> str:
    """
    生成缓存键（基于函数名和参数）
    
    Args:
        func_name: 函数名
        *args: 位置参数
        **kwargs: 关键字参数
        
    Returns:
        缓存键（字符串）
    """
    # 将参数序列化为字符串
    key_parts = [func_name]
    
    # 添加位置参数
    for arg in args:
        if isinstance(arg, (str, int, float, bool, type(None))):
            key_parts.append(str(arg))
        else:
            # 复杂对象使用hash
            try:
                key_parts.append(hashlib.md5(json.dumps(arg, sort_keys=True).encode()).hexdigest())
            except (TypeError, ValueError):
                key_parts.append(str(hash(str(arg))))
    
    # 添加关键字参数（排序以确保一致性）
    if kwargs:
        sorted_kwargs = sorted(kwargs.items())
        for key, value in sorted_kwargs:
            if isinstance(value, (str, int, float, bool, type(None))):
                key_parts.append(f"{key}={value}")
            else:
                try:
                    value_hash = hashlib.md5(json.dumps(value, sort_keys=True).encode()).hexdigest()
                    key_parts.append(f"{key}={value_hash}")
                except (TypeError, ValueError):
                    key_parts.append(f"{key}={hash(str(value))}")
    
    # 生成最终键
    key_str = "|".join(key_parts)
    return hashlib.md5(key_str.encode()).hexdigest()


def cache_result(
    cache_type: str = "result",
    ttl: Optional[int] = None,
    maxsize: Optional[int] = None
) -> Callable:
    """
    缓存装饰器
    
    使用示例：
        @cache_result(cache_type="result", ttl=300)
        def my_function(param1, param2):
            # 计算结果
            return result
    
    Args:
        cache_type: 缓存类型，"memory"（内存缓存，LRU）或 "result"（结果缓存，TTL）
        ttl: TTL（秒），仅用于result缓存类型
        maxsize: 最大缓存条目数，仅用于memory缓存类型
        
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        # 选择缓存实例
        if cache_type == "memory":
            cache = LRUCache(maxsize=maxsize or 256)
        else:  # result
            cache = _result_cache
            if ttl:
                # 为特定函数创建带TTL的缓存
                cache = TTLCache(default_ttl=ttl)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            func_name = f"{func.__module__}.{func.__name__}"
            cache_key = _generate_cache_key(func_name, *args, **kwargs)
            
            # 尝试从缓存获取
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # 缓存未命中，执行函数
            result = func(*args, **kwargs)
            
            # 存储到缓存
            if cache_type == "result" and isinstance(cache, TTLCache):
                cache.set(cache_key, result, ttl=ttl)
            else:
                cache.set(cache_key, result)
            
            return result
        
        # 添加缓存管理方法到包装函数
        wrapper.cache = cache
        wrapper.clear_cache = lambda: cache.clear()
        wrapper.get_cache_stats = lambda: cache.get_stats()
        
        return wrapper
    
    return decorator


def clear_cache(cache_type: Optional[str] = None) -> None:
    """
    清空缓存
    
    Args:
        cache_type: 缓存类型，"memory"、"result"或None（清空所有）
    """
    if cache_type == "memory" or cache_type is None:
        _memory_cache.clear()
    if cache_type == "result" or cache_type is None:
        _result_cache.clear()


def get_cache_stats(cache_type: Optional[str] = None) -> Dict[str, Any]:
    """
    获取缓存统计信息
    
    Args:
        cache_type: 缓存类型，"memory"、"result"或None（所有）
        
    Returns:
        缓存统计信息字典
    """
    if cache_type == "memory":
        return _memory_cache.get_stats()
    elif cache_type == "result":
        return _result_cache.get_stats()
    else:
        return {
            'memory': _memory_cache.get_stats(),
            'result': _result_cache.get_stats()
        }
