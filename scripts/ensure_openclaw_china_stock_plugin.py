#!/usr/bin/env python3
"""
将 openclaw-data-china-stock 写入 ~/.openclaw/openclaw.json：
  - plugins.allow 追加插件 id（若缺失）
  - plugins.entries.<id> 设为 { "enabled": true }（若缺失）

与 ensure_openclaw_plugin_load_paths.py 互补：后者负责 load.paths + option-trading-assistant。
本脚本仅处理数据采集扩展 id（openclaw.plugin.json 内 id）。

用法:
  python3 scripts/ensure_openclaw_china_stock_plugin.py --dry-run
  python3 scripts/ensure_openclaw_china_stock_plugin.py --ensure-allow --ensure-entry
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PLUGIN_ID = "openclaw-data-china-stock"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--config",
        default=os.path.expanduser("~/.openclaw/openclaw.json"),
        help="openclaw.json 路径",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ensure-allow", action="store_true")
    ap.add_argument("--ensure-entry", action="store_true")
    args = ap.parse_args()

    cfg_path = Path(args.config).expanduser()
    if not cfg_path.is_file():
        print(f"[ensure_openclaw_china_stock_plugin] 跳过：{cfg_path} 不存在", file=sys.stderr)
        return 0

    with cfg_path.open(encoding="utf-8") as f:
        data = json.load(f)

    plugins = data.setdefault("plugins", {})
    changed = False

    if args.ensure_allow:
        allow = plugins.setdefault("allow", [])
        if isinstance(allow, list) and PLUGIN_ID not in allow:
            allow.append(PLUGIN_ID)
            changed = True

    if args.ensure_entry:
        entries = plugins.setdefault("entries", {})
        if isinstance(entries, dict) and PLUGIN_ID not in entries:
            entries[PLUGIN_ID] = {"enabled": True}
            changed = True

    if args.dry_run:
        print(f"[ensure_openclaw_china_stock_plugin] dry-run allow 将含 {PLUGIN_ID}: ", end="")
        al = plugins.get("allow", [])
        print(PLUGIN_ID in al if isinstance(al, list) else "?")
        print(f"[ensure_openclaw_china_stock_plugin] dry-run entries[{PLUGIN_ID}]: ", end="")
        en = plugins.get("entries", {})
        print(en.get(PLUGIN_ID) if isinstance(en, dict) else "?")
        return 0

    if not changed:
        print(f"[ensure_openclaw_china_stock_plugin] 无需修改（已存在 {PLUGIN_ID}）")
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

    print(f"[ensure_openclaw_china_stock_plugin] 已更新 {cfg_path}（{PLUGIN_ID}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
