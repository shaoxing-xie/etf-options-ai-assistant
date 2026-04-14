#!/usr/bin/env python3
"""
切换 volatility_engine A/B profile 的小工具。

功能：
1) 一键切换 active_profile
2) 开/关 emergency_rollback_to_fusion
3) 打印当前配置与运行时生效参数
"""

import argparse
import re
import sys
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "environments" / "base.yaml"
sys.path.insert(0, str(PROJECT_ROOT))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _update_ab_test_fields(raw: str, profile: str | None, rollback: bool | None) -> str:
    lines = raw.splitlines()
    out: list[str] = []

    in_volatility_engine = False
    in_ab_test = False
    volatility_indent = -1
    ab_test_indent = -1
    active_updated = False
    rollback_updated = False

    for line in lines:
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)

        # 进入/退出 volatility_engine
        if re.match(r"^volatility_engine:\s*$", line):
            in_volatility_engine = True
            volatility_indent = indent
        elif in_volatility_engine and indent <= volatility_indent and stripped and not stripped.startswith("#"):
            in_volatility_engine = False
            in_ab_test = False

        # 进入/退出 ab_test
        if in_volatility_engine and re.match(r"^\s{2}ab_test:\s*$", line):
            in_ab_test = True
            ab_test_indent = indent
        elif in_ab_test and indent <= ab_test_indent and stripped and not stripped.startswith("#"):
            in_ab_test = False

        # 仅在 ab_test 块内替换目标字段
        if in_ab_test and profile is not None and re.match(r"^\s{4}active_profile:\s*", line):
            out.append(f"    active_profile: {profile}")
            active_updated = True
            continue

        if in_ab_test and rollback is not None and re.match(r"^\s{4}emergency_rollback_to_fusion:\s*", line):
            out.append(f"    emergency_rollback_to_fusion: {'true' if rollback else 'false'}")
            rollback_updated = True
            continue

        out.append(line)

    if profile is not None and not active_updated:
        raise RuntimeError("未找到 volatility_engine.ab_test.active_profile，请先确认 config/domains/analytics.yaml 结构。")
    if rollback is not None and not rollback_updated:
        raise RuntimeError("未找到 volatility_engine.ab_test.emergency_rollback_to_fusion，请先确认 config/domains/analytics.yaml 结构。")

    return "\n".join(out) + ("\n" if raw.endswith("\n") else "")


def _load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _print_status(cfg: dict) -> None:
    from src.volatility_range import _resolve_vol_engine_config

    ve = cfg.get("volatility_engine", {}) if isinstance(cfg, dict) else {}
    ab = ve.get("ab_test", {}) if isinstance(ve, dict) else {}
    profiles = ab.get("profiles", {}) if isinstance(ab, dict) else {}
    resolved = _resolve_vol_engine_config(cfg)

    print("=== config (merged) ===")
    print(f"active_profile: {ab.get('active_profile')}")
    print(f"emergency_rollback_to_fusion: {ab.get('emergency_rollback_to_fusion')}")
    print(f"available_profiles: {', '.join(sorted(profiles.keys())) if isinstance(profiles, dict) else ''}")
    print("=== runtime resolved ===")
    print(f"applied_profile: {resolved.get('_ab_profile_applied')}")
    print(f"rollback_active: {resolved.get('_ab_rollback_active')}")
    print(f"primary_method: {resolved.get('primary_method')}")
    print(f"garch_blend_weight: {resolved.get('garch_blend_weight')}")
    iv_cfg = resolved.get("iv_hv_fusion", {}) if isinstance(resolved.get("iv_hv_fusion"), dict) else {}
    vol_cfg = resolved.get("volume_adjustment", {}) if isinstance(resolved.get("volume_adjustment"), dict) else {}
    print(f"iv_hv(weight_iv/weight_hv): {iv_cfg.get('weight_iv')}/{iv_cfg.get('weight_hv')}")
    print(f"volume(influence,min,max): {vol_cfg.get('influence')}/{vol_cfg.get('min_factor')}/{vol_cfg.get('max_factor')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="切换 volatility_engine A/B profile")
    parser.add_argument("--profile", choices=["fusion_safe", "hybrid_balance", "garch_aggressive"], help="设置 active_profile")
    parser.add_argument(
        "--rollback",
        choices=["on", "off"],
        help="设置 emergency_rollback_to_fusion（on/off）",
    )
    parser.add_argument("--status", action="store_true", help="打印当前配置与运行时生效参数")
    args = parser.parse_args()

    if not CONFIG_PATH.exists():
        print(f"[error] config not found: {CONFIG_PATH}", file=sys.stderr)
        return 1

    if args.profile is None and args.rollback is None and not args.status:
        parser.print_help()
        return 0

    if args.profile is not None or args.rollback is not None:
        raw = _read_text(CONFIG_PATH)
        rollback_flag = None if args.rollback is None else (args.rollback == "on")
        updated = _update_ab_test_fields(raw, args.profile, rollback_flag)
        _write_text(CONFIG_PATH, updated)
        print(f"[ok] updated {CONFIG_PATH}")

    if args.status or args.profile is not None or args.rollback is not None:
        cfg = _load_config(CONFIG_PATH)
        _print_status(cfg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
