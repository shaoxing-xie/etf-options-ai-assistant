"""
进程内熔断器（无 Redis）：按 key 维度统计连续失败，OPEN 时快速失败。

默认关闭；开启方式：环境变量 OPENCLAW_CIRCUIT_BREAKER_ENABLED=1。
熔断开启时返回结构化 dict（便于工具链与 quality_status 对齐），不静默吞错。

宿主协同说明（为何本文件必须在 etf-options-ai-assistant 中存在）：
``plugins/data_collection`` 常通过符号链接指向 ``openclaw-data-china-stock`` 仓库，
其中 ``fetch_global.py`` 会 ``from plugins.utils.circuit_breaker import ...``。
Python 解析 ``plugins.utils`` 时使用**宿主仓库**的 ``plugins/utils`` 包，而不是
插件仓库里同名的 ``plugins/utils``。因此插件侧提交熔断实现后，若宿主未同步
本文件，会在运行时出现 ``ModuleNotFoundError``。本文件应与插件
``openclaw-data-china-stock/plugins/utils/circuit_breaker.py`` 保持语义一致；
``tests/test_plugins_utils_circuit_breaker_host_shim.py`` 防止回归。
"""

from __future__ import annotations

import os
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional

OPENCLAW_ENV_ENABLE = "OPENCLAW_CIRCUIT_BREAKER_ENABLED"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 60.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout_seconds = max(1.0, recovery_timeout_seconds)
        self.half_open_max_calls = max(1, half_open_max_calls)
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = 0.0
        self._half_open_calls = 0
        self._lock = threading.RLock()

    def allow_request(self) -> bool:
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if time.time() - self._opened_at >= self.recovery_timeout_seconds:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    return True
                return False
            # HALF_OPEN
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
            self._half_open_calls = 0

    def record_failure(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = time.time()
                self._half_open_calls = 0
                return
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.time()

    def state_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "state": self._state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self.failure_threshold,
            }

    def reset(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0
            self._opened_at = 0.0

    def would_block_next_call(self) -> bool:
        """Read-only：下一真实调用是否会被拒绝（不推进 HALF_OPEN 状态机）。"""
        with self._lock:
            now = time.time()
            if self._state == CircuitState.CLOSED:
                return False
            if self._state == CircuitState.OPEN:
                return now - self._opened_at < self.recovery_timeout_seconds
            # HALF_OPEN：探测名额已满则视同阻塞
            return self._half_open_calls >= self.half_open_max_calls


_BREAKERS: Dict[str, CircuitBreaker] = {}
_BREAKERS_LOCK = threading.RLock()


def _enabled_globally() -> bool:
    v = (os.getenv(OPENCLAW_ENV_ENABLE) or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def get_breaker(key: str) -> CircuitBreaker:
    with _BREAKERS_LOCK:
        if key not in _BREAKERS:
            ft = int(os.getenv("OPENCLAW_CB_FAILURE_THRESHOLD") or "5")
            rt = float(os.getenv("OPENCLAW_CB_RECOVERY_SECONDS") or "60")
            _BREAKERS[key] = CircuitBreaker(failure_threshold=ft, recovery_timeout_seconds=rt)
        return _BREAKERS[key]


def circuit_failure_payload(*, key: str, message: str = "") -> Dict[str, Any]:
    return {
        "success": False,
        "error_code": "CIRCUIT_OPEN",
        "error": message or f"circuit_open:{key}",
        "circuit_breaker": {"key": key, **get_breaker(key).state_snapshot()},
        "_meta": {
            "quality_status": "error",
            "circuit_open": True,
        },
    }


def call_or_pass_through(
    key: str,
    fn: Callable[[], Any],
    *,
    enabled: Optional[bool] = None,
) -> Any:
    """
    若熔断开启且全局 enable，则在 OPEN 时返回 circuit_failure_payload；
    否则执行 fn()。成功 record_success，异常 record_failure 后抛出。
    """
    use = _enabled_globally() if enabled is None else bool(enabled)
    if not use:
        return fn()
    br = get_breaker(key)
    if not br.allow_request():
        return circuit_failure_payload(key=key)
    try:
        out = fn()
        br.record_success()
        return out
    except Exception:
        br.record_failure()
        raise


def registry_snapshot() -> Dict[str, Any]:
    with _BREAKERS_LOCK:
        return {k: v.state_snapshot() for k, v in _BREAKERS.items()}


def reset_all_breakers_for_tests() -> None:
    """测试专用：清空 registry。"""
    with _BREAKERS_LOCK:
        _BREAKERS.clear()
