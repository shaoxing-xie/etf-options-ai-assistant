#!/usr/bin/env python3
from __future__ import annotations

import argparse
import faulthandler
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.analysis.six_index_next_day_predictor import build_l4, persist_l3, persist_l4, predict_all
from plugins.notification.send_dingtalk_message import tool_send_dingtalk_message
from src.config_loader import load_system_config
from src.features.six_index_features import build_feature_snapshot, persist_feature_snapshot
from src.prediction_recorder import record_prediction


def _format_report(l4_doc: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("## 六指数 14:00 次日方向预测")
    lines.append(f"交易日: {l4_doc.get('trade_date')}")
    lines.append(f"预测目标日: {l4_doc.get('predict_for_trade_date')}")
    lines.append("")
    hotspot_snapshot = l4_doc.get("hotspot_snapshot") if isinstance(l4_doc.get("hotspot_snapshot"), dict) else {}
    hotspots = hotspot_snapshot.get("hotspots") if isinstance(hotspot_snapshot.get("hotspots"), list) else []
    if hotspots:
        lines.append("### 今日热点TOP")
        for item in hotspots[:3]:
            lines.append(
                f"- {item.get('name')}: 热度 {item.get('heat_score')} / 理由 {', '.join(item.get('reasons') or [])}"
            )
        lines.append("")
    for row in l4_doc.get("predictions") or []:
        lines.append(
            f"- {row.get('index_name')}({row.get('index_code')}): "
            f"{row.get('direction')} / 概率 {row.get('probability')}% / "
            f"置信度 {row.get('confidence')} / 质量 {row.get('quality_status')}"
        )
        counterevidence = row.get("counterevidence") if isinstance(row.get("counterevidence"), list) else []
        if counterevidence:
            lines.append(f"  反向论证: {'；'.join(str(x) for x in counterevidence[:3])}")
    return "\n".join(lines)


def _notify_if_configured(message: str) -> Dict[str, Any]:
    webhook = (
        os.environ.get("DINGTALK_WEBHOOK_URL")
        or os.environ.get("DINGTALK_WEBHOOK")
        or os.environ.get("OPENCLAW_DINGTALK_CUSTOM_ROBOT_WEBHOOK_URL")
        or ""
    ).strip()
    secret = (
        os.environ.get("DINGTALK_SECRET")
        or os.environ.get("OPENCLAW_DINGTALK_CUSTOM_ROBOT_SECRET")
        or ""
    ).strip() or None
    if not webhook:
        return {"success": True, "skipped": True, "message": "missing webhook"}
    return tool_send_dingtalk_message(
        title="六指数次日方向预测",
        message=message,
        webhook_url=webhook,
        secret=secret,
        mode="prod",
        split_markdown_sections=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate six-index next trading day direction predictions.")
    parser.add_argument("--trade-date", default="", help="trade date in YYYY-MM-DD")
    parser.add_argument("--skip-notify", action="store_true")
    parser.add_argument("--watchdog-seconds", type=int, default=0, help="dump stack if run exceeds N seconds")
    args = parser.parse_args()

    if args.watchdog_seconds and args.watchdog_seconds > 0:
        def _watchdog():
            time.sleep(int(args.watchdog_seconds))
            print(f"WATCHDOG_TIMEOUT={args.watchdog_seconds}", flush=True)
            faulthandler.dump_traceback(file=sys.stderr)

        threading.Thread(target=_watchdog, daemon=True).start()

    cfg = load_system_config(use_cache=True)
    print("STAGE=build_features", flush=True)
    feature_doc = build_feature_snapshot(args.trade_date or None)
    print("STAGE=persist_features", flush=True)
    feature_path = persist_feature_snapshot(feature_doc)
    print("STAGE=predict_l3", flush=True)
    l3_doc = predict_all(feature_doc)
    print("STAGE=persist_l3", flush=True)
    l3_path = persist_l3(l3_doc)
    print("STAGE=build_l4", flush=True)
    l4_doc = build_l4(l3_doc)
    print("STAGE=persist_l4", flush=True)
    l4_path = persist_l4(l4_doc)
    hotspot_path = ROOT / "data" / "semantic" / "hotspot" / f"{l4_doc.get('trade_date')}.json"
    hotspot = l4_doc.get("hotspot_snapshot") if isinstance(l4_doc.get("hotspot_snapshot"), dict) else {}
    if hotspot:
        hotspot_path.parent.mkdir(parents=True, exist_ok=True)
        hotspot_path.write_text(json.dumps(hotspot, ensure_ascii=False, indent=2), encoding="utf-8")

    print("STAGE=record_predictions", flush=True)
    for row in l3_doc.get("predictions") or []:
        record_prediction(
            prediction_type="index_direction",
            symbol=str(row.get("index_code") or ""),
            prediction={
                "timestamp": l3_doc.get("_meta", {}).get("generated_at"),
                "method": row.get("model_family"),
                "confidence": row.get("confidence"),
                "direction": row.get("direction"),
                "probability": row.get("probability"),
                "quality_status": row.get("quality_status"),
                "reasoning": row.get("reasoning"),
                "signals": row.get("signals"),
                "score_breakdown": row.get("score_breakdown"),
            },
            source="scheduled",
            config=cfg,
            target_date=str(row.get("predict_for_trade_date") or ""),
            metadata={
                "index_name": row.get("index_name"),
                "task_id": "six-index-next-day-prediction",
                "trade_date": row.get("trade_date"),
            },
        )

    notify_result: Dict[str, Any] = {"success": True, "skipped": True, "message": "skip-notify"}
    if not args.skip_notify:
        print("STAGE=notify", flush=True)
        notify_result = _notify_if_configured(_format_report(l4_doc))
    print("STAGE=done", flush=True)

    print(f"FEATURES_PATH={feature_path}")
    print(f"L3_PATH={l3_path}")
    print(f"L4_PATH={l4_path}")
    if hotspot:
        print(f"HOTSPOT_PATH={hotspot_path}")
    print(f"NOTIFY_STATUS={'OK' if notify_result.get('success') else 'FAIL'}")
    print(f"NOTIFY_MESSAGE={notify_result.get('message')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
