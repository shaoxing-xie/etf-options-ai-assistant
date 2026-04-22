#!/usr/bin/env python3
"""
夜盘选股：调用 tool_screen_equity_factors → tool_finalize_screening_nightly（落盘 + 门禁 + 观察池）。

用法（项目根）:
  PYTHONPATH=. python3 scripts/nightly_screening_and_persist.py
  PYTHONPATH=. python3 scripts/nightly_screening_and_persist.py --universe hs300 --top-n 15
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from src.data_layer import MetaEnvelope, write_contract_json
from src.feature_flags import legacy_write_allowed

ROOT = Path(__file__).resolve().parents[1]


def _run_tool(name: str, args: dict) -> dict:
    exe = sys.executable
    runner = ROOT / "tool_runner.py"
    proc = subprocess.run(
        [exe, str(runner), name, json.dumps(args, ensure_ascii=False)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "tool failed")
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def _send_feishu_abnormal(title: str, lines: List[str]) -> Dict[str, Any]:
    msg = "\n".join([title] + [f"- {x}" for x in lines if str(x).strip()])
    try:
        return _run_tool(
            "tool_send_feishu_message",
            {
                "title": "夜盘选股异常告警",
                "message": msg,
                "cooldown_minutes": 0,
            },
        )
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"feishu_send_exception: {e}"}


def _read_artifact(path: str) -> Dict[str, Any]:
    p = Path(path or "")
    if not p.is_file():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _build_processing_report(
    *,
    screen: Dict[str, Any],
    fin: Dict[str, Any],
    artifact: Dict[str, Any],
    run_at_utc: str,
) -> tuple[str, List[str]]:
    summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    rows = list(screen.get("data") or [])
    top_score = rows[0].get("score") if rows else None
    top_symbol = rows[0].get("symbol") if rows else None
    quality = screen.get("quality_score")
    degraded = bool(screen.get("degraded"))
    inactive = screen.get("inactive_factors_runtime") or []
    gate_reasons = artifact.get("gate_reasons") if isinstance(artifact.get("gate_reasons"), list) else []
    watchlist_skipped = artifact.get("watchlist_skipped") if isinstance(artifact.get("watchlist_skipped"), list) else []

    critical_issues: List[str] = []
    warning_issues: List[str] = []
    if not bool(screen.get("success")):
        critical_issues.append(f"上游选股执行失败：{screen.get('message') or screen.get('error') or 'unknown'}")
    if degraded:
        critical_issues.append(f"上游数据降级：quality_score={quality}")
    if isinstance(inactive, list) and inactive:
        warning_issues.append(f"因子打分不全：inactive_factors={inactive}")
    if not bool(fin.get("success")):
        critical_issues.append(f"落盘/收尾失败：{fin.get('message')}")
    if gate_reasons:
        warning_issues.append(f"观察池门禁阻断：gate_reasons={gate_reasons}")
    if watchlist_skipped:
        warning_issues.append(f"观察池写入跳过：watchlist_skipped={watchlist_skipped}")

    all_issues = critical_issues + warning_issues
    if critical_issues:
        status = "异常"
        impact = "输出结果受影响（红灯）"
    elif warning_issues:
        status = "关注"
        impact = "输出部分受限（黄灯，建议复核）"
    else:
        status = "处理正常"
        impact = "输出可信度正常（绿灯）"

    title = f"[nightly-stock-screening] {status}（{run_at_utc} UTC）"
    lines = [
        f"运行状态：screen_success={screen.get('success')} finalize_success={fin.get('success')}",
        f"运行质量：quality_score={quality} degraded={degraded}",
        f"产出摘要：universe_size={screen.get('universe_size')} top_symbol={top_symbol} top_score={top_score}",
        f"业务影响：{impact}",
    ]
    if all_issues:
        lines.append("影响分项（按优先级）：")
        lines.extend([f"{i + 1}. {it}" for i, it in enumerate(critical_issues)])
        lines.extend([f"{len(critical_issues) + i + 1}. {it}" for i, it in enumerate(warning_issues)])
        if critical_issues:
            lines.append("处置建议：优先修复上游故障/降级，再处理口径与门禁问题。")
        else:
            lines.append("处置建议：建议复核Top标的，并尽快修复行业口径或缺失因子来源。")
    else:
        lines.append("影响分项：无")
        lines.append("处置建议：维持现网策略并持续监控。")
    # 兜底：若 artifact 含 summary，可补充推荐数量
    if isinstance(summary, dict) and summary:
        lines.append(
            "结果统计："
            f"recommended={summary.get('recommended_count')} "
            f"watch={summary.get('watch_count')} ignored={summary.get('ignored_count')}"
        )
    return title, lines


def _factor_is_flat_neutral(rows: List[Dict[str, Any]], factor: str) -> bool:
    vals: List[float] = []
    all_raw_none = True
    for row in rows:
        f = ((row or {}).get("factors") or {}).get(factor) or {}
        score = f.get("score")
        raw = f.get("raw")
        if raw is not None:
            all_raw_none = False
        try:
            vals.append(float(score))
        except (TypeError, ValueError):
            vals.append(50.0)
    if not vals:
        return True
    # 全体都在默认中性分（50）附近，可视为该因子本轮无信息增益
    all_50 = all(abs(v - 50.0) < 1e-9 for v in vals)
    return all_50 or all_raw_none


def _renormalize_with_effective_factors(screen: Dict[str, Any]) -> Dict[str, Any]:
    rows = list(screen.get("data") or [])
    weights = dict(screen.get("weights_effective") or {})
    req_factors = list(screen.get("factors_requested") or [])
    if not rows or not weights or not req_factors:
        return screen

    inactive: Set[str] = set()
    for f in req_factors:
        if _factor_is_flat_neutral(rows, f):
            inactive.add(f)

    active = [f for f in req_factors if f not in inactive and f in weights]
    if not active:
        return screen
    if len(active) == len(req_factors):
        return screen

    wsum = sum(float(weights.get(f, 0.0)) for f in active) or 1.0
    renorm = {f: float(weights.get(f, 0.0)) / wsum for f in active}
    for row in rows:
        factors = (row or {}).get("factors") or {}
        total = 0.0
        for f in active:
            sf = (factors.get(f) or {}).get("score")
            try:
                total += renorm[f] * float(sf)
            except (TypeError, ValueError):
                total += renorm[f] * 50.0
        row["score"] = round(total, 4)

    rows.sort(key=lambda x: float((x or {}).get("score") or 0.0), reverse=True)
    screen["data"] = rows
    screen["weights_effective_runtime"] = renorm
    screen["inactive_factors_runtime"] = sorted(inactive)
    screen["message"] = (
        f"{screen.get('message', 'ok')} | runtime_reweight applied "
        f"(active={active}, inactive={sorted(inactive)})"
    )
    return screen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="hs300")
    ap.add_argument("--top-n", type=int, default=15)
    ap.add_argument("--max-universe-size", type=int, default=50)
    args = ap.parse_args()

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    screen: Dict[str, Any] = {}
    fin: Dict[str, Any] = {}
    try:
        screen = _run_tool(
            "tool_screen_equity_factors",
            {
                "universe": args.universe,
                "regime_hint": "oscillation",
                "top_n": args.top_n,
                "max_universe_size": args.max_universe_size,
                "factors": ["reversal_5d", "fund_flow_3d", "sector_momentum_5d"],
                "neutralize": [],
            },
        )
        screen = _renormalize_with_effective_factors(screen if isinstance(screen, dict) else {})
        if legacy_write_allowed("nightly-stock-screening"):
            fin = _run_tool(
                "tool_finalize_screening_nightly",
                {"screening_result": screen, "attempt_watchlist": True},
            )
        else:
            fin = {
                "success": True,
                "message": "legacy finalize disabled by feature flag",
                "artifact_path": "",
                "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
            }
    except Exception as e:  # noqa: BLE001
        when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fei = _send_feishu_abnormal(
            f"[nightly-stock-screening] 执行异常（{when} UTC）",
            [f"exception={type(e).__name__}: {e}"],
        )
        print(json.dumps({"screen": False, "finalize": {"success": False, "message": str(e)}, "abnormal_notify": fei}, ensure_ascii=False, indent=2))
        return 1

    art = _read_artifact(str(fin.get("artifact_path") or ""))
    try:
        _persist_new_data_layer(screen=screen, fin=fin, artifact=art)
    except Exception as e:  # noqa: BLE001
        # Keep legacy flow alive; treat new-layer persistence failure as warning.
        print(json.dumps({"new_layer_warning": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    title, report_lines = _build_processing_report(screen=screen, fin=fin, artifact=art, run_at_utc=when)
    fei: Dict[str, Any] = _send_feishu_abnormal(title, report_lines)

    print(
        json.dumps(
            {"screen": screen.get("success"), "finalize": fin, "abnormal_notify": fei},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if fin.get("success") and screen.get("success") else 1


def _persist_new_data_layer(*, screen: Dict[str, Any], fin: Dict[str, Any], artifact: Dict[str, Any]) -> None:
    trade_date = str((artifact or {}).get("run_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    run_id = str((fin or {}).get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    quality_status = "degraded" if bool((screen or {}).get("degraded")) else "ok"

    recommendations_path = ROOT / "data" / "decisions" / "recommendations" / f"nightly_{trade_date}.json"
    write_contract_json(
        recommendations_path,
        payload={
            "run_date": trade_date,
            "screening": screen,
            "artifact": artifact,
        },
        meta=MetaEnvelope(
            schema_name="screening_candidates_v1",
            schema_version="1.0.0",
            task_id="nightly-stock-screening",
            run_id=run_id,
            data_layer="L3",
            trade_date=trade_date,
            quality_status=quality_status,
            lineage_refs=[str(fin.get("artifact_path") or "")],
            source_tools=["tool_screen_equity_factors", "tool_finalize_screening_nightly"],
        ),
    )

    watchlist = _read_artifact(str(ROOT / "data" / "watchlist" / "default.json"))
    write_contract_json(
        ROOT / "data" / "decisions" / "watchlist" / "current.json",
        payload=watchlist if isinstance(watchlist, dict) else {},
        meta=MetaEnvelope(
            schema_name="watchlist_state_v1",
            schema_version="1.0.0",
            task_id="nightly-stock-screening",
            run_id=run_id,
            data_layer="L3",
            trade_date=trade_date,
            quality_status=quality_status,
            lineage_refs=[str(ROOT / "data" / "watchlist" / "default.json")],
            source_tools=["tool_finalize_screening_nightly"],
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
