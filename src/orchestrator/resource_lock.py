"""方案 §9：同刻多 job 争用时对编排关键段的进程内文件锁（fcntl）。"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def advisory_file_lock(
    lock_path: Path,
    *,
    wait_seconds: float = 0.1,
    acquire_timeout_seconds: float = 3600.0,
) -> Generator[None, None, None]:
    """
    非阻塞尝试失败后短睡重试，直到 acquire_timeout_seconds。
    测试或紧急旁路：环境变量 ORCHESTRATOR_NO_FILE_LOCK=1 则 no-op。
    """
    if os.environ.get("ORCHESTRATOR_NO_FILE_LOCK", "").strip() in ("1", "true", "yes"):
        yield
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + max(1.0, float(acquire_timeout_seconds))
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if getattr(e, "errno", None) not in (errno.EAGAIN, errno.EACCES):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"orchestrator_lock_timeout:{lock_path}") from e
                time.sleep(wait_seconds)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
