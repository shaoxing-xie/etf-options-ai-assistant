"""
性能监控模块
提供工具执行时间统计和系统资源监控功能

支持：
- 工具执行时间统计
- 慢工具识别
- 系统资源监控（CPU、内存、磁盘、网络）
"""

import time
import functools
import threading
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from collections import defaultdict, deque
import sqlite3
from pathlib import Path
import os

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# 执行时间统计存储（内存）
_execution_times: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))  # 每个工具最多保存1000条记录
_execution_times_lock = threading.RLock()

# 慢工具阈值（秒）
SLOW_TOOL_THRESHOLD = 5.0


def measure_execution_time(func: Optional[Callable] = None, tool_name: Optional[str] = None) -> Callable:
    """
    执行时间统计装饰器
    
    使用示例：
        @measure_execution_time(tool_name="my_tool")
        def my_tool(param1, param2):
            # 工具逻辑
            return result
    
    Args:
        func: 被装饰的函数（装饰器参数）
        tool_name: 工具名称（如果为None，使用函数名）
    
    Returns:
        装饰器函数
    """
    def decorator(f: Callable) -> Callable:
        tool = tool_name or f.__name__
        
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            start_cpu = _get_cpu_time() if PSUTIL_AVAILABLE else None
            
            try:
                result = f(*args, **kwargs)
                success = True
                error = None
            except Exception as e:
                result = None
                success = False
                error = str(e)
                raise
            finally:
                elapsed_time = time.time() - start_time
                end_cpu = _get_cpu_time() if PSUTIL_AVAILABLE else None
                
                # 记录执行时间
                record = {
                    'timestamp': datetime.now().isoformat(),
                    'elapsed_time': elapsed_time,
                    'success': success,
                    'error': error,
                    'cpu_time': (end_cpu - start_cpu) if (start_cpu and end_cpu) else None,
                }
                
                with _execution_times_lock:
                    _execution_times[tool].append(record)
            
            return result
        
        return wrapper
    
    if func is None:
        return decorator
    else:
        return decorator(func)


def _get_cpu_time() -> Optional[float]:
    """获取当前进程的CPU时间（用户态+内核态）"""
    if not PSUTIL_AVAILABLE:
        return None
    try:
        process = psutil.Process()
        cpu_times = process.cpu_times()
        return cpu_times.user + cpu_times.system
    except Exception:
        return None


def get_execution_stats(tool_name: Optional[str] = None, hours: int = 24) -> Dict[str, Any]:
    """
    获取执行时间统计信息
    
    Args:
        tool_name: 工具名称（如果为None，返回所有工具的统计）
        hours: 统计时间范围（小时）
    
    Returns:
        统计信息字典
    """
    cutoff_time = datetime.now() - timedelta(hours=hours)
    
    with _execution_times_lock:
        if tool_name:
            # 单个工具的统计
            records = _execution_times.get(tool_name, deque())
            return _calculate_stats(records, cutoff_time, tool_name)
        else:
            # 所有工具的统计
            all_stats = {}
            for tool, records in _execution_times.items():
                stats = _calculate_stats(records, cutoff_time, tool)
                if stats['total_calls'] > 0:
                    all_stats[tool] = stats
            return all_stats


def _calculate_stats(records: deque, cutoff_time: datetime, tool_name: str) -> Dict[str, Any]:
    """计算统计信息"""
    if not records:
        return {
            'tool_name': tool_name,
            'total_calls': 0,
            'successful_calls': 0,
            'failed_calls': 0,
            'avg_time': 0.0,
            'min_time': 0.0,
            'max_time': 0.0,
            'p50_time': 0.0,
            'p90_time': 0.0,
            'p99_time': 0.0,
        }
    
    # 过滤时间范围内的记录
    filtered_records = [
        r for r in records
        if datetime.fromisoformat(r['timestamp']) >= cutoff_time
    ]
    
    if not filtered_records:
        return {
            'tool_name': tool_name,
            'total_calls': 0,
            'successful_calls': 0,
            'failed_calls': 0,
            'avg_time': 0.0,
            'min_time': 0.0,
            'max_time': 0.0,
            'p50_time': 0.0,
            'p90_time': 0.0,
            'p99_time': 0.0,
        }
    
    times = [r['elapsed_time'] for r in filtered_records]
    successful = sum(1 for r in filtered_records if r.get('success', False))
    failed = len(filtered_records) - successful
    
    sorted_times = sorted(times)
    n = len(sorted_times)
    
    return {
        'tool_name': tool_name,
        'total_calls': n,
        'successful_calls': successful,
        'failed_calls': failed,
        'success_rate': (successful / n * 100) if n > 0 else 0.0,
        'avg_time': sum(times) / n,
        'min_time': min(times),
        'max_time': max(times),
        'p50_time': sorted_times[n // 2] if n > 0 else 0.0,
        'p90_time': sorted_times[int(n * 0.9)] if n > 0 else 0.0,
        'p99_time': sorted_times[int(n * 0.99)] if n > 0 else 0.0,
    }


def get_slow_tools(threshold: float = SLOW_TOOL_THRESHOLD, hours: int = 24) -> List[Dict[str, Any]]:
    """
    识别慢工具（执行时间超过阈值的工具）
    
    Args:
        threshold: 慢工具阈值（秒）
        hours: 统计时间范围（小时）
    
    Returns:
        慢工具列表（按平均执行时间降序排列）
    """
    all_stats = get_execution_stats(hours=hours)
    slow_tools = []
    
    for tool_name, stats in all_stats.items():
        if stats['avg_time'] > threshold:
            slow_tools.append(stats)
    
    # 按平均执行时间降序排列
    slow_tools.sort(key=lambda x: x['avg_time'], reverse=True)
    
    return slow_tools


def clear_execution_stats(tool_name: Optional[str] = None):
    """
    清除执行时间统计
    
    Args:
        tool_name: 工具名称（如果为None，清除所有工具的统计）
    """
    with _execution_times_lock:
        if tool_name:
            if tool_name in _execution_times:
                _execution_times[tool_name].clear()
        else:
            _execution_times.clear()


# 系统资源监控
class SystemResourceMonitor:
    """系统资源监控类"""
    
    def __init__(self):
        self.enabled = PSUTIL_AVAILABLE
        self._resources: deque = deque(maxlen=1000)  # 最多保存1000条记录
        self._lock = threading.RLock()
    
    def collect(self) -> Dict[str, Any]:
        """
        收集系统资源使用情况
        
        Returns:
            资源使用情况字典
        """
        if not self.enabled:
            return {
                'enabled': False,
                'message': 'psutil not available'
            }
        
        try:
            process = psutil.Process()
            
            # CPU使用率
            cpu_percent = process.cpu_percent(interval=0.1)
            
            # 内存使用
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            memory_percent = process.memory_percent()
            
            # 系统级别资源
            system_cpu = psutil.cpu_percent(interval=0.1)
            system_memory = psutil.virtual_memory()
            
            # 磁盘使用（当前工作目录所在磁盘）
            try:
                disk_usage = psutil.disk_usage('.')
                disk_percent = disk_usage.percent
            except Exception:
                disk_percent = None
            
            resource_data = {
                'timestamp': datetime.now().isoformat(),
                'process': {
                    'cpu_percent': cpu_percent,
                    'memory_mb': memory_mb,
                    'memory_percent': memory_percent,
                },
                'system': {
                    'cpu_percent': system_cpu,
                    'memory_percent': system_memory.percent,
                    'disk_percent': disk_percent,
                }
            }
            
            with self._lock:
                self._resources.append(resource_data)
            
            return resource_data
            
        except Exception as e:
            return {
                'enabled': True,
                'error': str(e)
            }
    
    def get_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        获取资源使用统计
        
        Args:
            hours: 统计时间范围（小时）
        
        Returns:
            统计信息字典
        """
        if not self.enabled:
            return {'enabled': False}
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        with self._lock:
            filtered_resources = [
                r for r in self._resources
                if datetime.fromisoformat(r['timestamp']) >= cutoff_time
            ]
        
        if not filtered_resources:
            return {
                'enabled': True,
                'total_samples': 0
            }
        
        # 计算统计信息
        process_cpu_values = [r['process']['cpu_percent'] for r in filtered_resources]
        process_memory_values = [r['process']['memory_mb'] for r in filtered_resources]
        system_cpu_values = [r['system']['cpu_percent'] for r in filtered_resources]
        system_memory_values = [r['system']['memory_percent'] for r in filtered_resources]
        
        return {
            'enabled': True,
            'total_samples': len(filtered_resources),
            'process': {
                'cpu': {
                    'avg': sum(process_cpu_values) / len(process_cpu_values),
                    'max': max(process_cpu_values),
                    'min': min(process_cpu_values),
                },
                'memory_mb': {
                    'avg': sum(process_memory_values) / len(process_memory_values),
                    'max': max(process_memory_values),
                    'min': min(process_memory_values),
                }
            },
            'system': {
                'cpu': {
                    'avg': sum(system_cpu_values) / len(system_cpu_values),
                    'max': max(system_cpu_values),
                    'min': min(system_cpu_values),
                },
                'memory': {
                    'avg': sum(system_memory_values) / len(system_memory_values),
                    'max': max(system_memory_values),
                    'min': min(system_memory_values),
                }
            }
        }
    
    def clear(self):
        """清除资源监控数据"""
        with self._lock:
            self._resources.clear()


# 全局资源监控实例
_resource_monitor = SystemResourceMonitor()


def get_resource_monitor() -> SystemResourceMonitor:
    """获取全局资源监控实例"""
    return _resource_monitor
