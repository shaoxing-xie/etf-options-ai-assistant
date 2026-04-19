#!/usr/bin/env python3
"""
一次性计时：复现 cron「tool_send_etf_rotation_research_report」路径各环节耗时。
默认 mode=test（不发钉钉/网络），与生产相同的计算与报告组装逻辑。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"
for p in (str(PLUGINS), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_env() -> None:
    try:
        from utils.env_loader import load_env_file
    except ImportError:
        return
    load_env_file(ROOT / ".env", override=False)
    load_env_file(Path.home() / ".openclaw" / ".env", override=False)


def main() -> int:
    _load_env()

    pipeline_runs: list[dict[str, object]] = []

    import analysis.etf_rotation_research as err_mod

    _orig_rp = err_mod.run_rotation_pipeline

    def _wrapped_rp(*args, **kwargs):
        t0 = perf_counter()
        eng = kwargs.get("score_engine", "?")
        out = _orig_rp(*args, **kwargs)
        dt = perf_counter() - t0
        pipeline_runs.append({"score_engine": eng, "seconds": round(dt, 3)})
        return out

    err_mod.run_rotation_pipeline = _wrapped_rp  # type: ignore[assignment]

    # 须在 patch 之后再 import，保证 tool_etf_rotation_research 闭包外调用的仍是 err_mod 全局名
    import notification.send_etf_rotation_research as ser_mod

    _orig_send = ser_mod.tool_send_analysis_report
    send_s: dict[str, float] = {}

    def _wrapped_send(*args, **kwargs):
        t0 = perf_counter()
        try:
            return _orig_send(*args, **kwargs)
        finally:
            send_s["seconds"] = round(perf_counter() - t0, 3)

    ser_mod.tool_send_analysis_report = _wrapped_send  # type: ignore[assignment]

    t_all = perf_counter()
    out = ser_mod.tool_send_etf_rotation_research_report(
        etf_pool="",
        lookback_days=120,
        top_k=3,
        mode="test",
    )
    total = perf_counter() - t_all

    report = {
        "success": out.get("success"),
        "skipped": out.get("skipped"),
        "message": out.get("message"),
        "total_seconds": round(total, 3),
        "run_rotation_pipeline_calls": pipeline_runs,
        "sum_pipeline_seconds": round(sum(float(x["seconds"]) for x in pipeline_runs), 3),
        "tool_send_analysis_report_seconds": send_s.get("seconds"),
        "other_under_wrapper_estimate_seconds": round(
            total - sum(float(x["seconds"]) for x in pipeline_runs) - float(send_s.get("seconds") or 0.0),
            3,
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if out.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
