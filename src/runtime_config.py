"""
运行时配置管理与在线热加载

提供：
- get_runtime_config(): 线程安全获取当前运行配置
- reload_runtime_config_and_reschedule(): 重新加载配置并根据需要重建 scheduler 任务
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from threading import RLock, Thread

from src.logger_config import get_module_logger
from src.config_loader import load_system_config, reload_config_cache
from src.scheduler_registry import (
    get_scheduler as get_registered_scheduler,
    register_scheduler,
    register_scheduler_thread,
)

logger = get_module_logger(__name__)

_runtime_config: Optional[Dict[str, Any]] = None
_lock = RLock()


def get_runtime_config() -> Dict[str, Any]:
    """
    获取当前运行时配置。

    优先返回已缓存的运行时配置；如果尚未初始化，则从 config.yaml 加载。
    """
    global _runtime_config
    with _lock:
        if _runtime_config is None:
            logger.debug("运行时配置未初始化，正在从文件加载...")
            _runtime_config = load_system_config(use_cache=False)
        return _runtime_config


def _set_runtime_config(cfg: Dict[str, Any]) -> None:
    global _runtime_config
    with _lock:
        _runtime_config = cfg


def reload_runtime_config_and_reschedule() -> Dict[str, Any]:
    """
    在线加载最新配置，并根据需要重建/更新 scheduler 任务。

    返回:
        dict: {success: bool, message: str, details: {...}}
    """
    try:
        logger.info("开始在线加载配置并更新调度任务...")

        # 清除底层缓存，确保从磁盘重读
        reload_config_cache()

        new_cfg = load_system_config(use_cache=False)
        _set_runtime_config(new_cfg)

        # 更新 scheduler 任务：先获取旧实例，再根据新配置创建并启动新实例
        old_scheduler = get_registered_scheduler()
        try:
            from main import setup_scheduler  # type: ignore

            # 创建新的 scheduler 并根据新配置添加任务
            new_scheduler = setup_scheduler(new_cfg)
            register_scheduler(new_scheduler)

            # 启动新 scheduler（在后台线程中运行）
            def _run_scheduler():
                try:
                    new_scheduler.start()
                except Exception as e:
                    logger.error(f"新调度器运行出错: {e}", exc_info=True)

            t = Thread(target=_run_scheduler, name="scheduler-reloaded-thread", daemon=True)
            t.start()
            # 注册线程，便于 Web/API 查询时诊断 scheduler 是否仍在运行
            try:
                register_scheduler_thread(t)
            except Exception:
                pass

            # 关闭旧 scheduler（如果存在）
            if old_scheduler is not None and getattr(old_scheduler, "running", False):
                try:
                    old_scheduler.shutdown(wait=False)
                    logger.info("旧调度任务已关闭。")
                except Exception as e:
                    logger.warning(f"关闭旧调度任务时发生错误: {e}", exc_info=True)

            logger.info("调度任务已根据新配置重新创建并启动。")
            return {
                "success": True,
                "message": "配置已重载并重建调度任务。",
                "details": {
                    "scheduler_updated": True,
                },
            }
        except Exception as e:
            logger.warning(f"更新调度任务时发生错误: {e}", exc_info=True)
            return {
                "success": True,
                "message": f"配置已重载，但更新调度任务时出现问题: {e}",
                "details": {
                    "scheduler_updated": False,
                },
            }
    except Exception as e:
        logger.error(f"在线加载配置失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"在线加载配置失败: {e}",
            "details": {},
        }

