#!/usr/bin/env python3
"""
从 config/tools_manifest.yaml 生成 config/tools_manifest.json，供 OpenClaw 插件 index 加载。
单一数据源：修改 manifest 后运行此脚本再重启/重载插件。

用法示例（在项目根目录执行）：
  # 生成 tools_manifest.json（需安装 PyYAML）
  python3 scripts/generate_tools_json.py

  # 常见：改了 config/tools_manifest.yaml 后先生成，再重启/重载 OpenClaw Gateway
"""
from pathlib import Path
import json
import sys

try:
    import yaml
except ImportError:
    print("需要 PyYAML: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_YAML = REPO_ROOT / "config" / "tools_manifest.yaml"
MANIFEST_JSON = REPO_ROOT / "config" / "tools_manifest.json"


def main() -> None:
    if not MANIFEST_YAML.exists():
        print(f"未找到 {MANIFEST_YAML}", file=sys.stderr)
        sys.exit(1)
    with open(MANIFEST_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    # 确保 parameters 中 required 为列表（YAML 可能解析为列表）
    for tool in data.get("tools", []):
        params = tool.get("parameters") or {}
        if "required" in params and params["required"] is None:
            params["required"] = []
    with open(MANIFEST_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已生成 {MANIFEST_JSON}，共 {len(data.get('tools', []))} 个工具。")


if __name__ == "__main__":
    main()
