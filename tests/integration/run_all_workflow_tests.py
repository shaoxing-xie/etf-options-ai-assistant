#!/usr/bin/env python3
"""
统一测试所有定时工作流的脚本。

目标：
- 串行调用 `workflows/` 目录下的各个 *step_by_step / *enhanced 测试脚本
- 汇总每个工作流脚本的退出码，并打印简要通过/失败情况

注意：
- 每个子脚本本身已经有详细的步骤级日志和结果文件，这里只做“冒烟”和总览。
"""

import subprocess
import sys
from pathlib import Path


# 项目根目录（本文件位于 tests/integration/）
ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / "workflows"

# 要运行的工作流测试脚本（相对 workflows/）
WORKFLOW_SCRIPTS = [
    "test_before_open_analysis_step_by_step.py",
    "test_after_close_analysis_step_by_step.py",
    "test_intraday_monitor_5min_step_by_step.py",
    "test_signal_generation_on_demand_step_by_step.py",
    "test_before_open_enhanced_step_by_step.py",
    "test_after_close_enhanced_step_by_step.py",
]


def run_workflow_script(script_rel_path: str) -> int:
    script_path = WORKFLOWS_DIR / script_rel_path
    print("\n" + "=" * 100)
    print(f"运行工作流脚本: {script_rel_path}")
    print("=" * 100)

    if not script_path.exists():
        print(f"✗ 脚本不存在: {script_path}")
        return 1

    cmd = [sys.executable, str(script_path)]
    print("命令:", " ".join(cmd))

    proc = subprocess.run(
        cmd,
        cwd=str(WORKFLOWS_DIR),
        text=True,
    )
    exit_code = proc.returncode
    if exit_code == 0:
        print(f"✓ 脚本执行完成: {script_rel_path} (exit_code={exit_code})")
    else:
        print(f"✗ 脚本执行失败: {script_rel_path} (exit_code={exit_code})")
    return exit_code


def main() -> None:
    print("=" * 100)
    print("运行所有定时工作流测试脚本 (tests/integration/run_all_workflow_tests.py)")
    print("=" * 100)

    results = {}
    for script in WORKFLOW_SCRIPTS:
        code = run_workflow_script(script)
        results[script] = code

    print("\n" + "=" * 100)
    print("工作流汇总结果")
    print("=" * 100)
    failed = []
    for script, code in results.items():
        status = "OK" if code == 0 else "FAIL"
        print(f"{status:4} - {script} (exit_code={code})")
        if code != 0:
            failed.append(script)

    if failed:
        print("\n有工作流脚本执行失败：")
        for script in failed:
            print(f"- {script}")
        # 整体退出码设为 1，便于 CI 或人工一眼看出有问题
        sys.exit(1)
    else:
        print("\n✓ 所有工作流脚本执行成功")
        sys.exit(0)


if __name__ == "__main__":
    main()

