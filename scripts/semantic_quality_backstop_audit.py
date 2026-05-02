#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ["sentiment_snapshot", "screening_candidates", "screening_view", "ops_events", "rotation_latest"]
DEGRADED_STREAK_THRESHOLD = 5
SILENCE_SECONDS = 3600
STALE_FALLBACK_HOURS = 24
DATASET_EXPECTED_READY_AT_SH = {
    # 09:10 任务后给少量缓冲，避免刚触发时误报
    "sentiment_snapshot": time(9, 15),
    # 夜盘选股是晚间任务，白天巡检不应要求已有当日产物
    "screening_candidates": time(20, 5),
    # 14:00 尾盘选股落盘后给少量缓冲
    "screening_view": time(14, 5),
    # 16:35 运维快照落盘；16:30 backstop 不应抢跑
    "ops_events": time(16, 40),
    # 16:15 启动且可能运行较久，给更宽松完成窗口
    "rotation_latest": time(16, 45),
}


def _ensure_repo_syspath() -> None:
    r = str(ROOT)
    if r not in sys.path:
        sys.path.insert(0, r)


def _resolve_expected_trade_date_hyphen(now: datetime) -> str | None:
    """与日线/盘后 L4 对齐的期望交易日（YYYY-MM-DD，上海口径）。失败时返回 None 以触发回退逻辑。"""
    try:
        _ensure_repo_syspath()
        from src.system_status import get_expected_latest_a_share_daily_bar_date

        ymd = get_expected_latest_a_share_daily_bar_date(now)
        if not ymd or len(ymd) != 8 or not ymd.isdigit():
            return None
        return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    except Exception:
        return None


def _previous_trading_day_hyphen(now: datetime) -> str | None:
    """返回上海口径的上一交易日（YYYY-MM-DD）。"""
    fallback = (now.astimezone(timezone(timedelta(hours=8))) - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        _ensure_repo_syspath()
        from src.system_status import get_last_trading_day_on_or_before

        ref = now - timedelta(days=1)
        ymd = get_last_trading_day_on_or_before(ref)
        if not ymd or len(ymd) != 8 or not ymd.isdigit():
            return fallback
        return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    except Exception:
        return fallback


def _resolve_dataset_expected_trade_date_hyphen(
    now: datetime,
    dataset: str,
    default_expected_trade_date: str | None,
) -> str | None:
    """
    按数据集自身产出时点推导当下应有的最新 trade_date。

    例：16:30 跑 backstop 时，不应要求 20:00 才产出的 nightly 数据集
    已经达到当日 trade_date。
    """
    cutoff = DATASET_EXPECTED_READY_AT_SH.get(dataset)
    if cutoff is None or default_expected_trade_date is None:
        return default_expected_trade_date
    try:
        sh_now = now.astimezone(timezone(timedelta(hours=8)))
    except Exception:
        return default_expected_trade_date
    if sh_now.time() >= cutoff:
        return default_expected_trade_date
    previous_trade_date = _previous_trading_day_hyphen(now)
    return previous_trade_date or default_expected_trade_date


def _snapshot_stale(
    now: datetime,
    latest_trade_date: str,
    generated_at: datetime | None,
    expected_trade_date: str | None,
) -> tuple[bool, str]:
    """
    主判据：最新快照文件名 trade_date（stem）是否落后于「当前时刻应对齐到的 A 股交易日」。
    回退：无法解析交易日历时，沿用 generated_at 超过 STALE_FALLBACK_HOURS 的墙钟判定。
    """
    if expected_trade_date and len(latest_trade_date) == 10 and latest_trade_date[4] == "-" and latest_trade_date[7] == "-":
        if latest_trade_date < expected_trade_date:
            return True, "trade_calendar_lag"
        return False, "trade_calendar_ok"
    if generated_at is not None:
        if now - generated_at > timedelta(hours=STALE_FALLBACK_HOURS):
            return True, "generated_at_wall_clock"
        return False, "generated_at_ok"
    return False, "unknown_no_generated_at"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _extract_payload_meta(obj: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
    meta = obj.get("_meta") if isinstance(obj.get("_meta"), dict) else {}
    if not data and any(k != "_meta" for k in obj.keys()):
        data = {k: v for k, v in obj.items() if k != "_meta"}
    return data, meta


def _latest_n_files(path: Path, n: int = 10) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted([p for p in path.glob("*.json") if p.is_file()])[-n:]


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_generated_at(meta: dict[str, Any], trade_date: str) -> datetime | None:
    raw = str(meta.get("generated_at") or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None
    if trade_date:
        try:
            return datetime.fromisoformat(f"{trade_date}T00:00:00+00:00").astimezone(timezone.utc)
        except Exception:
            return None
    return None


def _load_silence_state(path: Path) -> dict[str, Any]:
    return _read_json(path) if path.is_file() else {}


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _send_feishu(title: str, message: str) -> dict[str, Any]:
    runner = ROOT / "tool_runner.py"
    if not runner.is_file():
        return {"success": False, "message": "tool_runner_missing", "failure_stage": "delivery"}
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(runner),
                "tool_send_feishu_message",
                json.dumps({"title": title, "message": message, "cooldown_minutes": 0}, ensure_ascii=False),
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            return {"success": False, "message": proc.stderr or proc.stdout or "tool_failed", "failure_stage": "delivery"}
        out = json.loads(proc.stdout.strip() or "{}")
        return {"success": bool(out.get("success")), "message": out.get("message", "ok"), "failure_stage": "delivery"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": str(e), "failure_stage": "delivery"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Semantic quality backstop audit (L4 snapshots)")
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="不调用飞书、不在静默窗口内更新 silence（由 run_quality_backstop_audit_cli 统一摘要投递）",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    silence_file = ROOT / "data" / "meta" / "monitoring" / "semantic_alert_silence.json"
    evidence_dir = ROOT / "data" / "meta" / "evidence"
    report_path = ROOT / "data" / "meta" / "monitoring" / f"semantic_quality_{today}.json"

    silence_state = _load_silence_state(silence_file)
    findings: list[dict[str, Any]] = []
    alert_items: list[dict[str, Any]] = []
    expected_trade_date = _resolve_expected_trade_date_hyphen(now)

    for dataset in DATASETS:
        base = ROOT / "data" / "semantic" / dataset
        files = _latest_n_files(base, n=12)
        if not files:
            findings.append(
                {
                    "dataset": dataset,
                    "trade_date": today,
                    "status": "error",
                    "failure_stage": "snapshot",
                    "reason": "snapshot_missing",
                }
            )
            alert_items.append(findings[-1])
            continue
        newest_path = files[-1]
        newest_stem = newest_path.stem
        newest_obj = _read_json(newest_path)
        _, newest_meta = _extract_payload_meta(newest_obj)
        quality = str((newest_meta or {}).get("quality_status") or "ok")
        generated_at = _parse_generated_at(newest_meta, newest_stem)

        streak = 0
        for p in reversed(files):
            _, meta = _extract_payload_meta(_read_json(p))
            if str((meta or {}).get("quality_status") or "ok") == "degraded":
                streak += 1
            else:
                break

        dataset_expected_trade_date = _resolve_dataset_expected_trade_date_hyphen(now, dataset, expected_trade_date)
        stale, stale_basis = _snapshot_stale(now, newest_stem, generated_at, dataset_expected_trade_date)
        entry = {
            "dataset": dataset,
            "trade_date": newest_stem,
            "status": quality,
            "degraded_streak": streak,
            "stale": stale,
            "stale_basis": stale_basis,
            "failure_stage": "",
            "reason": "",
        }
        # Extra schema/field checks for specific datasets (additive, backward compatible).
        if dataset == "rotation_latest":
            newest_data, _ = _extract_payload_meta(newest_obj)
            recs = newest_data.get("recommendations") if isinstance(newest_data, dict) else None
            if recs is not None:
                # If recommendations exist, enforce minimal per-item fields (cautions/allocation_pct/signals).
                bad = 0
                if isinstance(recs, list):
                    for r in recs[:10]:
                        if not isinstance(r, dict):
                            bad += 1
                            continue
                        if "cautions" not in r or "allocation_pct" not in r:
                            bad += 1
                else:
                    bad = 1
                if bad > 0:
                    entry["status"] = "degraded"
                    entry["failure_stage"] = "monitoring"
                    entry["reason"] = "rotation_recommendations_invalid"
        if dataset_expected_trade_date:
            entry["expected_trade_date"] = dataset_expected_trade_date
        eff_quality = str(entry.get("status") or quality or "ok")
        if eff_quality == "error":
            entry["failure_stage"] = "monitoring"
            entry["reason"] = entry.get("reason") or "quality_status_error"
            alert_items.append(entry)
        elif entry.get("failure_stage") == "monitoring" and entry.get("reason"):
            # Dataset-specific degraded-but-actionable checks (e.g. schema expectations).
            alert_items.append(entry)
        elif streak >= DEGRADED_STREAK_THRESHOLD:
            entry["failure_stage"] = "monitoring"
            entry["reason"] = f"degraded_streak_{streak}"
            alert_items.append(entry)
        elif stale:
            entry["failure_stage"] = "monitoring"
            entry["reason"] = "sla_timeout"
            alert_items.append(entry)
        findings.append(entry)

    alerts_to_send: list[dict[str, Any]] = []
    for item in alert_items:
        ds = item.get("dataset")
        last_epoch = float(silence_state.get(ds) or 0)
        if now.timestamp() - last_epoch >= SILENCE_SECONDS:
            alerts_to_send.append(item)
            if not args.no_notify:
                silence_state[ds] = int(now.timestamp())

    delivery: dict[str, Any] = {"success": True, "message": "no_alert"}
    if alerts_to_send and not args.no_notify:
        lines = [
            f"{it['dataset']}@{it.get('trade_date')}: {it.get('reason') or it.get('status')}"
            for it in alerts_to_send
        ]
        delivery = _send_feishu(
            title="语义层质量告警（quality_backstop_audit）",
            message="触发数据集:\n" + "\n".join(f"- {x}" for x in lines),
        )
    elif alerts_to_send and args.no_notify:
        delivery = {
            "success": True,
            "message": "deferred_to_cli",
            "alerts": len(alerts_to_send),
        }

    report = {
        "generated_at": _iso_now(),
        "rule": {
            "degraded_streak_threshold": DEGRADED_STREAK_THRESHOLD,
            "silence_seconds": SILENCE_SECONDS,
            "stale_policy": {
                "primary": "latest_snapshot_stem_vs_dataset_adjusted_expected_trade_date",
                "base_trade_date_source": "get_expected_latest_a_share_daily_bar_date",
                "dataset_ready_at_sh": {
                    k: v.strftime("%H:%M") for k, v in DATASET_EXPECTED_READY_AT_SH.items()
                },
                "fallback_hours": STALE_FALLBACK_HOURS,
                "fallback_when": "invalid_stem_or_expected_trade_date_unresolved",
            },
        },
        "results": findings,
        "alerts_emitted": alerts_to_send,
        "delivery": delivery,
    }
    _save_json(report_path, report)
    _save_json(silence_file, silence_state)
    _save_json(evidence_dir / f"semantic_quality_evidence_{today}.json", report)
    print(json.dumps({"success": True, "report": str(report_path), "alerts": len(alerts_to_send)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
