#!/usr/bin/env python3
"""
本脚本用于“第三方用户可读文档”的快速环境自检。

它不做任何写操作（除了读取本地/用户目录存在性），主要用于帮助用户在执行
`install_plugin.sh` 前确认关键前置条件是否满足。
"""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from typing import Iterable, Tuple


def _try_imports(modules: Iterable[str]) -> Tuple[bool, list[str]]:
    missing: list[str] = []
    for m in modules:
        try:
            importlib.import_module(m)
        except Exception:
            missing.append(m)
    return (len(missing) == 0, missing)


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    home = Path.home()

    ok_all = True

    # 1) Python 版本
    if sys.version_info >= (3, 8):
        print("✅ Python版本检查通过")
    else:
        ok_all = False
        print("❌ Python版本不满足要求（需要 >= 3.8）")

    # 2) OpenClaw CLI / 目录存在性
    openclaw_bin = shutil.which("openclaw")
    openclaw_dir = home / ".openclaw"
    if openclaw_bin and openclaw_dir.exists():
        print("✅ OpenClaw路径检查通过")
    else:
        ok_all = False
        if not openclaw_bin:
            print("❌ 未检测到 `openclaw` 命令（请先安装 OpenClaw）")
        if not openclaw_dir.exists():
            print("❌ `~/.openclaw/` 目录不存在（请先完成 OpenClaw 基础部署）")

    # 3) 关键目录存在性（本项目）
    required_paths = [
        repo_root / "install_plugin.sh",
        repo_root / "tool_runner.py",
        repo_root / "memory",
        repo_root / "data",
    ]
    missing_paths = [str(p) for p in required_paths if not p.exists()]
    if not missing_paths:
        print("✅ 关键目录/缓存路径检查通过")
    else:
        ok_all = False
        print("❌ 缺少关键文件/目录：")
        for p in missing_paths:
            print(f"  - {p}")

    # 4) 依赖包检查（只做“import 可用性”）
    # 注意：为了速度，这里检查一组最关键的依赖；完整依赖由 install_plugin.sh 处理。
    required_modules = ["numpy", "pandas", "requests", "yaml", "akshare", "pytz"]
    deps_ok, missing = _try_imports(required_modules)
    if deps_ok:
        print("✅ 依赖包检查通过")
    else:
        ok_all = False
        print("❌ 缺少依赖包或无法 import（将由 install_plugin.sh 尝试补齐）：")
        for m in missing:
            print(f"  - {m}")

    if ok_all:
        print("✅ 所有检查通过，可以开始安装")
        return 0

    print("⚠️ 以上检查未全部通过。你仍然可以继续执行 `bash install_plugin.sh`，但建议先按提示处理。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

