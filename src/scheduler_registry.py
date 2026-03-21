"""
Scheduler 全局注册表
用于在多线程环境下安全地访问 scheduler 实例及其运行线程。
"""

from __future__ import annotations

from typing import Optional
from threading import Thread
from apscheduler.schedulers.blocking import BlockingScheduler

# 全局scheduler实例
_scheduler: Optional[BlockingScheduler] = None
_scheduler_thread: Optional[Thread] = None


def register_scheduler(scheduler_instance: BlockingScheduler) -> None:
    """
    注册scheduler实例
    
    Args:
        scheduler_instance: BlockingScheduler实例
    """
    global _scheduler
    _scheduler = scheduler_instance


def register_scheduler_thread(thread: Thread) -> None:
    """
    注册运行 scheduler.start() 的线程，便于诊断“任务不再执行”的问题。
    """
    global _scheduler_thread
    _scheduler_thread = thread


def get_scheduler() -> Optional[BlockingScheduler]:
    """
    获取scheduler实例（线程安全）
    
    Returns:
        BlockingScheduler: scheduler实例，如果未注册则返回None
    """
    global _scheduler
    return _scheduler


def get_scheduler_thread() -> Optional[Thread]:
    """
    获取运行 scheduler.start() 的线程（如果有）。
    """
    global _scheduler_thread
    return _scheduler_thread


def is_scheduler_available() -> bool:
    """
    检查scheduler是否可用
    
    Returns:
        bool: True如果scheduler已注册且正在运行，否则False
    """
    global _scheduler
    return _scheduler is not None and hasattr(_scheduler, 'running') and _scheduler.running
