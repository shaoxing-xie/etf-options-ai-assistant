#!/usr/bin/env python3
"""
Cron 入口：按 Asia/Shanghai 日历日调用 verify_predictions，无 shell/cd/&&，可通过 OpenClaw exec 预检。

用法（由 jobs.json 引用）:
    python3 scripts/run_verify_predictions_cron.py
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    print("VERIFY_STATUS=FAIL", flush=True)
    print("VERIFY_DATE=UNKNOWN", flush=True)
    print("RECORDS_VERIFIED=0", flush=True)
    print("ACCURACY=UNAVAILABLE", flush=True)
    print("REPORT_PATH=NONE", flush=True)
    print("ROOT_CAUSE=Python<3.9_missing_zoneinfo", flush=True)
    sys.exit(1)


def _load_verify_module(project_root: Path):
    path = project_root / "scripts" / "verify_predictions.py"
    spec = importlib.util.spec_from_file_location("verify_predictions_cron", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    parser = argparse.ArgumentParser(description="Cron wrapper for prediction verification")
    parser.add_argument("--mode", choices=["all", "direction"], default="all")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    mod = _load_verify_module(project_root)
    json_file = mod.PREDICTION_RECORDS_DIR / f"predictions_{date}.json"

    if args.mode == "direction":
        stats = mod.verify_direction_predictions_for_target_date(date)
    else:
        if not json_file.exists():
            print("VERIFY_STATUS=PARTIAL", flush=True)
            print(f"VERIFY_DATE={date}", flush=True)
            print("RECORDS_VERIFIED=0", flush=True)
            print("ACCURACY=UNAVAILABLE", flush=True)
            print("REPORT_PATH=NONE", flush=True)
            print(f"PREDICTIONS_JSON_MISSING={json_file}", flush=True)
            return 0
        stats = mod.verify_predictions_for_date(date, None)

    verified = int(stats.get("verified") or 0)
    acc = stats.get("accuracy")
    acc_s = f"{float(acc):.6f}" if verified > 0 and acc is not None else "UNAVAILABLE"

    report_name = f"direction_verification_{date}.md" if args.mode == "direction" else f"verification_{date}.md"
    report_path = project_root / "data" / "verification_reports" / report_name
    if verified > 0:
        if args.mode == "direction":
            report = "\n".join(
                [
                    f"## 方向验证报告 - {date}",
                    "",
                    f"- 已验证: {verified}",
                    f"- 命中: {int(stats.get('hit') or 0)}",
                    f"- 未命中: {int(stats.get('miss') or 0)}",
                    f"- 准确率: {float(acc):.2%}",
                ]
            )
        else:
            report = mod.generate_verification_report(date, stats)
        print(report, flush=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        status = "OK"
        rp = str(report_path)
    else:
        status = "PARTIAL"
        rp = "NONE"

    print("VERIFY_STATUS=" + status, flush=True)
    print(f"VERIFY_DATE={date}", flush=True)
    print(f"RECORDS_VERIFIED={verified}", flush=True)
    print(f"ACCURACY={acc_s}", flush=True)
    print(f"VERIFY_MODE={args.mode}", flush=True)
    print(f"REPORT_PATH={rp}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("VERIFY_STATUS=FAIL", flush=True)
        print("VERIFY_DATE=UNKNOWN", flush=True)
        print("RECORDS_VERIFIED=0", flush=True)
        print("ACCURACY=UNAVAILABLE", flush=True)
        print("REPORT_PATH=NONE", flush=True)
        print(f"ROOT_CAUSE={e!s}", flush=True)
        raise SystemExit(1)
