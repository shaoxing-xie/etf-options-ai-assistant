#!/usr/bin/env python3
"""
直连调用 tool_run_data_cache_job（不经 LLM），供 cron 单 exec 链路基线。

用于「轮动池预热」等场景：避免 OpenClaw 未热加载 jobs.json 时仍注入旧 payload，
又保证飞书摘要与 assistant 工具路径一致。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI wrapper for tool_run_data_cache_job")
    parser.add_argument(
        "--job",
        required=True,
        choices=["morning_daily", "intraday_minute", "close_minute"],
        help="data_cache 阶段",
    )
    parser.add_argument("--throttle-stock", action="store_true")
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="跳过飞书（默认 morning_daily/close_minute 会 notify）",
    )
    parser.add_argument(
        "--feishu-title",
        default="",
        help="可选：飞书标题覆盖（如 轮动池预热补缓存完成）",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    from src.data_cache_collection_core import (
        feishu_notify_title_and_body_for_cache_job,
        run_data_cache_collection,
        summary_success,
    )

    notify = False if args.no_notify else (args.job in {"morning_daily", "close_minute"})
    summary = run_data_cache_collection(args.job, throttle_stock=bool(args.throttle_stock))
    collection_ok = summary_success(summary)
    degraded_reasons: list[str] = []
    out = {
        # 语义：success 表示“采集是否成功”；通知失败属于降级，不应让 cron 标红为 error。
        "success": collection_ok,
        "collection_success": collection_ok,
        "job": args.job,
        "notify": notify,
        "notify_result": None,
        "run_quality": "ok_full" if collection_ok else "error",
        "degraded_reasons": degraded_reasons,
        "summary": summary,
    }
    if notify:
        from plugins.merged.send_feishu_notification import tool_send_feishu_notification

        title, body = feishu_notify_title_and_body_for_cache_job(
            args.job,
            summary,
            collection_ok=collection_ok,
            title_override=(args.feishu_title or "").strip() or None,
        )
        notify_result = tool_send_feishu_notification(
            title=title,
            message=body,
            notification_type="message",
        )
        out["notify_result"] = notify_result
        if not bool(notify_result.get("success")):
            degraded_reasons.append("notify_failed")
            if collection_ok:
                out["run_quality"] = "ok_degraded"
        else:
            out["run_quality"] = "ok_full" if collection_ok else "error"

    print(json.dumps(out, ensure_ascii=False, indent=2))
    # cron 退出码：以采集成功为准；通知失败按 degraded 处理。
    sys.exit(0 if collection_ok else 1)


if __name__ == "__main__":
    main()
