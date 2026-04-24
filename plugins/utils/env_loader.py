"""
加载 .env 文件到 os.environ；优先 python-dotenv，不可用时用极简 KEY=VALUE 解析。
override=False：已存在的环境变量不被覆盖（与 dotenv 默认一致）。
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path, *, override: bool = False) -> None:
    if not path.is_file():
        return
    # 单元测试应保持可复现：避免本机 ~/.openclaw/.env 影响测试分支（例如启用某些外部数据源）。
    try:
        if os.getenv("PYTEST_CURRENT_TEST") and path == (Path.home() / ".openclaw" / ".env"):
            return
    except Exception:
        pass
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]

        load_dotenv(path, override=override)
        # 规范写法为 `KEY=VALUE`。这里保留对历史 `export KEY=...` 的兼容解析，
        # 仅用于平滑迁移（补齐缺失键，且遵循 override 语义）。
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return
        for line in raw.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("export "):
                s = s[7:].strip()
            if "=" not in s:
                continue
            k, _, v = s.partition("=")
            k = k.strip()
            v = v.strip()
            if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
                v = v[1:-1]
            if not k:
                continue
            if not override and os.getenv(k):
                continue
            os.environ[k] = v
        return
    except ImportError:
        pass
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].strip()
        if "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        if not k:
            continue
        if not override and os.getenv(k):
            continue
        os.environ[k] = v
