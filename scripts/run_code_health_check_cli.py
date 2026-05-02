#!/usr/bin/env python3
"""
直连：跑 shared 的 code_health_autofix.py，并按约定格式发飞书（不经 LLM）。

避免 code_maintenance_agent 在第二轮工具前输出非标准 token（如 to=functions.read）
导致 OpenInference 报错、任务 status=error 且无飞书。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHARED = Path("/home/xie/.openclaw/workspaces/shared")
DEFAULT_VENV_PY = ROOT / ".venv" / "bin" / "python"


def _parse_report_paths(stdout: str, report_dir: Path, stamp: str) -> tuple[Path, Path]:
    md_m = re.search(r"^report_md=(.+)$", stdout, re.MULTILINE)
    js_m = re.search(r"^report_json=(.+)$", stdout, re.MULTILINE)
    if md_m and js_m:
        return Path(md_m.group(1).strip()), Path(js_m.group(1).strip())
    return (
        report_dir / f"code-health-autofix-{stamp}.md",
        report_dir / f"code-health-autofix-{stamp}.json",
    )


def build_feishu_body(
    data: dict[str, object],
    report_md: Path,
    report_json: Path,
    *,
    tz_name: str,
) -> tuple[str, str]:
    """返回 (title, message_body)；message 为飞书正文（不含 [message] 前缀，由合并工具加）。"""
    title = "每日代码健康体检"
    auto_fixed = int(data.get("auto_fixed_count") or 0)
    bare = int(data.get("bare_except_fixed") or 0)

    lines: list[str] = []
    lines.append("每日代码健康体检已完成。\n")
    fix_line = f"已自动修复：{auto_fixed} 项。"
    if bare:
        fix_line += f"（bare-except 规范化：{bare} 处）"
    lines.append(fix_line)

    lines.append("\n未修复问题：")
    unresolved: list[str] = []
    rr = data.get("ruff_remaining")
    if isinstance(rr, list) and len(rr) > 0:
        unresolved.append(f"- Ruff: {len(rr)} 处未自动修复（详见 JSON ruff_remaining）")

    raw_m = data.get("mypy")
    mypy: dict[str, object] = raw_m if isinstance(raw_m, dict) else {}
    if int(mypy.get("returncode", 0) or 0) != 0:
        unresolved.append("- MyPy: 返回码非 0，需人工复核")

    raw_p = data.get("pytest")
    pytest: dict[str, object] = raw_p if isinstance(raw_p, dict) else {}
    if int(pytest.get("returncode", 0) or 0) != 0:
        unresolved.append("- Pytest: 返回码非 0，需人工复核")

    raw_b = data.get("bandit")
    bandit: dict[str, object] = raw_b if isinstance(raw_b, dict) else {}
    brc = int(bandit.get("returncode", 0) or 0)
    if brc != 0:
        unresolved.append(f"- Bandit: 返回码 {brc}，需人工复核（安全检查）")

    if not unresolved:
        unresolved.append("- 无阻塞项（若有低危 Bandit 提示，见 JSON）")
    lines.extend(unresolved)

    p0: list[str] = []
    p1: list[str] = []
    p2: list[str] = []
    if int(pytest.get("returncode", 0) or 0) != 0:
        p0.append("Pytest 失败修复")
    if int(mypy.get("returncode", 0) or 0) != 0:
        p0.append("MyPy 类型问题")
    if brc != 0:
        p0.append("Bandit 安全检查")
    if isinstance(rr, list) and len(rr) > 0:
        p1.append("Ruff 未自动修复项")
    if not p0 and not p1:
        p2.append("无")
    elif not p2:
        p2.append("无")

    def _join(xs: list[str]) -> str:
        return "、".join(xs) if xs else "无"

    lines.append("\n建议人工修复优先级：")
    lines.append(f"- P0：{_join(p0)}；P1：{_join(p1)}；P2：{_join(p2)}。")

    lines.append("\n报告文件:")
    lines.append(f"- Markdown: {report_md}")
    lines.append(f"- JSON: {report_json}")

    tz = ZoneInfo(tz_name)
    head_ts = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    # 合并工具会再加一行「时间:」；此处正文顶行给出上海时间便于扫读
    body = f"（上海 {head_ts}）\n\n" + "\n".join(lines)
    return title, body


def main() -> None:
    parser = argparse.ArgumentParser(description="Run shared code health check and optional Feishu notify")
    parser.add_argument("--shared-root", type=Path, default=DEFAULT_SHARED, help="shared workspace 根目录")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=None,
        help="报告目录（默认 <shared-root>/memory）",
    )
    parser.add_argument("--venv-python", type=Path, default=DEFAULT_VENV_PY, help="用于执行 autofix 的 Python")
    parser.add_argument("--no-notify", action="store_true", help="跳过飞书，仅跑体检脚本")
    parser.add_argument("--tz", default="Asia/Shanghai", help="摘要里展示用的时区")
    args = parser.parse_args()

    shared: Path = args.shared_root.resolve()
    report_dir = (args.report_dir or (shared / "memory")).resolve()
    stamp = datetime.now().strftime("%Y-%m-%d")
    venv_py = args.venv_python.resolve()
    script = shared / "tools" / "code_health_autofix.py"

    if not script.is_file():
        print(json.dumps({"success": False, "error": f"missing script: {script}"}, ensure_ascii=False))
        sys.exit(1)
    if not venv_py.is_file():
        print(json.dumps({"success": False, "error": f"missing venv python: {venv_py}"}, ensure_ascii=False))
        sys.exit(1)

    proc = subprocess.run(
        [str(venv_py), str(script), "--root", str(shared), "--report-dir", str(report_dir)],
        cwd=str(shared),
        text=True,
        capture_output=True,
        timeout=900,
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    report_md, report_json = _parse_report_paths(proc.stdout or "", report_dir, stamp)

    result: dict[str, object] = {
        "success": proc.returncode == 0,
        "exit_code": proc.returncode,
        "report_md": str(report_md),
        "report_json": str(report_json),
        "autofix_tail": (proc.stdout or "")[-2000:],
    }

    if proc.returncode != 0:
        result["stderr"] = (proc.stderr or "")[-4000:]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    if not report_json.is_file():
        result["success"] = False
        result["error"] = f"report json missing: {report_json}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    data = json.loads(report_json.read_text(encoding="utf-8"))
    title, body = build_feishu_body(data, report_md, report_json, tz_name=args.tz)
    result["feishu_title"] = title

    if args.no_notify:
        result["notify_skipped"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)

    sys.path.insert(0, str(ROOT))
    from plugins.merged.send_feishu_notification import tool_send_feishu_notification

    notify = tool_send_feishu_notification(
        "message",
        title=title,
        message=body,
        cooldown_minutes=0,
        cooldown_key=f"code-health-daily:{stamp}",
    )
    result["notify_result"] = notify
    ok = bool(notify.get("success"))
    result["success"] = ok
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
