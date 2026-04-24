#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ["sentiment_snapshot", "screening_candidates", "screening_view", "ops_events", "rotation_latest"]
DEGRADED_STREAK_THRESHOLD = 5
SILENCE_SECONDS = 3600


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
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    silence_file = ROOT / "data" / "meta" / "monitoring" / "semantic_alert_silence.json"
    evidence_dir = ROOT / "data" / "meta" / "evidence"
    report_path = ROOT / "data" / "meta" / "monitoring" / f"semantic_quality_{today}.json"

    silence_state = _load_silence_state(silence_file)
    findings: list[dict[str, Any]] = []
    alert_items: list[dict[str, Any]] = []

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
        streak = 0
        latest_meta: dict[str, Any] = {}
        latest_trade_date = ""
        for p in reversed(files):
            _, meta = _extract_payload_meta(_read_json(p))
            latest_meta = meta or latest_meta
            latest_trade_date = p.stem
            if str((meta or {}).get("quality_status") or "ok") == "degraded":
                streak += 1
            else:
                break
        quality = str((latest_meta or {}).get("quality_status") or "ok")
        generated_at = _parse_generated_at(latest_meta, latest_trade_date)
        stale = False
        if generated_at is not None:
            stale = now - generated_at > timedelta(hours=24)
        entry = {
            "dataset": dataset,
            "trade_date": latest_trade_date,
            "status": quality,
            "degraded_streak": streak,
            "stale": stale,
            "failure_stage": "",
            "reason": "",
        }
        if quality == "error":
            entry["failure_stage"] = "monitoring"
            entry["reason"] = "quality_status_error"
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
            silence_state[ds] = int(now.timestamp())

    delivery = {"success": True, "message": "no_alert"}
    if alerts_to_send:
        lines = [
            f"{it['dataset']}@{it.get('trade_date')}: {it.get('reason') or it.get('status')}"
            for it in alerts_to_send
        ]
        delivery = _send_feishu(
            title="语义层质量告警（quality_backstop_audit）",
            message="触发数据集:\n" + "\n".join(f"- {x}" for x in lines),
        )

    report = {
        "generated_at": _iso_now(),
        "rule": {
            "degraded_streak_threshold": DEGRADED_STREAK_THRESHOLD,
            "silence_seconds": SILENCE_SECONDS,
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
