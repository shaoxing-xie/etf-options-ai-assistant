#!/usr/bin/env python3
"""
将本仓库与 ~/.openclaw/extensions 写入 openclaw.json 的 plugins.load.paths（去重、绝对路径）。

OpenClaw 2026.4.x 下，仅通过 extensions 下的符号链接可能无法把 option-trading-assistant
纳入 knownIds，导致 plugins.allow 报 plugin not found。推荐在 load.paths 中加入本仓库真实路径。

可选：同步 plugins.allow / plugins.entries 中的 option-trading-assistant（新环境一键就绪）。

用法示例（在项目根目录执行）：
  # 干跑：仅打印将写入的 paths，不落盘
  python3 scripts/ensure_openclaw_plugin_load_paths.py --dry-run

  # 实际写入 ~/.openclaw/openclaw.json（并补齐 allow/entry）
  python3 scripts/ensure_openclaw_plugin_load_paths.py --ensure-allow --ensure-entry
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


PLUGIN_ID = "option-trading-assistant"


def _real(p: str) -> str:
    return str(Path(p).expanduser().resolve(strict=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--config",
        default=os.path.expanduser("~/.openclaw/openclaw.json"),
        help="openclaw.json 路径",
    )
    ap.add_argument(
        "--repo-root",
        default=None,
        help="etf-options-ai-assistant 仓库根目录（默认：本脚本所在仓库）",
    )
    ap.add_argument(
        "--extensions-dir",
        default=None,
        help="OpenClaw 扩展目录（默认：$OPENCLAW_EXTENSIONS_DIR 或 ~/.openclaw/extensions）",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要写入的路径，不写文件",
    )
    ap.add_argument(
        "--ensure-allow",
        action="store_true",
        help="若 plugins.allow 中缺少 %s 则追加" % PLUGIN_ID,
    )
    ap.add_argument(
        "--ensure-entry",
        action="store_true",
        help="若 plugins.entries 缺少 %s 则添加 enabled: true" % PLUGIN_ID,
    )
    args = ap.parse_args()

    cfg_path = Path(args.config).expanduser()
    if not cfg_path.is_file():
        print(f"[ensure_openclaw_plugin_load_paths] 跳过：配置文件不存在 {cfg_path}", file=sys.stderr)
        return 0

    repo = _real(args.repo_root or str(Path(__file__).resolve().parent.parent))
    ext = _real(
        args.extensions_dir
        or os.environ.get("OPENCLAW_EXTENSIONS_DIR")
        or str(Path.home() / ".openclaw" / "extensions")
    )

    required = [ext, repo]
    with cfg_path.open(encoding="utf-8") as f:
        data = json.load(f)

    plugins = data.setdefault("plugins", {})
    load = plugins.setdefault("load", {})
    raw_paths = load.get("paths")
    if raw_paths is None:
        paths: list[str] = []
    elif not isinstance(raw_paths, list):
        print("[ensure_openclaw_plugin_load_paths] plugins.load.paths 不是数组，退出", file=sys.stderr)
        return 1
    else:
        paths = list(raw_paths)

    seen: set[str] = set()
    merged: list[str] = []
    for p in paths + required:
        if not isinstance(p, str) or not p.strip():
            continue
        key = _real(p)
        if key in seen:
            continue
        seen.add(key)
        merged.append(key)

    changed = merged != paths
    if changed:
        load["paths"] = merged

    if args.ensure_allow:
        allow = plugins.setdefault("allow", [])
        if not isinstance(allow, list):
            print("[ensure_openclaw_plugin_load_paths] plugins.allow 不是数组，跳过 --ensure-allow", file=sys.stderr)
        elif PLUGIN_ID not in allow:
            allow.append(PLUGIN_ID)
            changed = True

    if args.ensure_entry:
        entries = plugins.setdefault("entries", {})
        if not isinstance(entries, dict):
            print(
                "[ensure_openclaw_plugin_load_paths] plugins.entries 不是对象，跳过 --ensure-entry",
                file=sys.stderr,
            )
        elif PLUGIN_ID not in entries:
            entries[PLUGIN_ID] = {"enabled": True}
            changed = True

    print("[ensure_openclaw_plugin_load_paths] plugins.load.paths:")
    for p in load.get("paths", []):
        print(f"  - {p}")

    if args.dry_run:
        print("[ensure_openclaw_plugin_load_paths] dry-run：未写回文件")
        return 0

    if not changed:
        print("[ensure_openclaw_plugin_load_paths] 无需修改")
        return 0

    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(prefix="openclaw-", suffix=".json", dir=str(cfg_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(tmp, cfg_path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    print(f"[ensure_openclaw_plugin_load_paths] 已更新 {cfg_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
