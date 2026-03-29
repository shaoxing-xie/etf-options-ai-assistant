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
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]

        load_dotenv(path, override=override)
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
