"""
data_cache 批量采集核心逻辑（与 scripts/run_data_cache_collection.py 行为一致）。

供 CLI 与 OpenClaw 合并工具 `tool_run_data_cache_job` 共用，避免双份实现。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple

Phase = Literal["morning_daily", "intraday_minute", "close_minute"]


def rotation_aligned_daily_window_calendar_days() -> Tuple[str, str]:
    """
    与 `etf_rotation_core.run_rotation_pipeline` 的日线加载窗对齐量级（cal_back 上限约 1200 日历日），
    保证采集写入的 parquet 覆盖轮动/回测常见 lookback+corr+MA。
    """
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=850)).strftime("%Y-%m-%d")
    return start, end


def summary_success(summary: Dict[str, Any]) -> bool:
    """与 run_data_cache_collection.main() 中 exit code 判定一致。"""
    return all(
        s.get("success") is not False
        for s in summary.get("steps", [])
        if isinstance(s.get("success"), bool)
    )


def run_data_cache_collection(
    phase: Phase,
    *,
    throttle_stock: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    执行采集并返回 summary dict（与 CLI 打印的 JSON 结构一致）。

    Args:
        phase: morning_daily | intraday_minute | close_minute
        throttle_stock: 仅 intraday_minute：为 True 时仅当当前分钟为 1 或 31 才拉股票分钟
        now: 可选，用于测试注入上海时区的「当前」时刻；默认 None 表示 datetime.now(Asia/Shanghai)
    """
    import pytz

    from src.config_loader import load_system_config
    from src.data_cache_universe import get_data_cache_universe

    config = load_system_config(use_cache=True)
    u = get_data_cache_universe(config)

    summary: Dict[str, Any] = {"phase": phase, "universe": u, "steps": []}

    def _run_daily_historical_block() -> None:
        from plugins.data_collection.index.fetch_historical import tool_fetch_index_historical
        from plugins.data_collection.etf.fetch_historical import tool_fetch_etf_historical
        from plugins.data_collection.stock.fetch_historical import tool_fetch_stock_historical
        from src.data_cache import (
            save_etf_daily_cache,
            save_index_daily_cache,
            save_stock_daily_cache,
        )
        from src.tushare_fallback import (
            fetch_etf_daily_tushare,
            fetch_index_daily_tushare,
            fetch_stock_daily_tushare,
        )

        start, end = rotation_aligned_daily_window_calendar_days()
        start_ymd = start.replace("-", "")
        end_ymd = end.replace("-", "")
        cfg = load_system_config(use_cache=True)

        def _prefer_tushare_daily(
            codes: List[str],
            fetch_func: Any,
            save_func: Any,
            kind_label: str,
        ) -> Tuple[List[str], List[str]]:
            ts_ok: List[str] = []
            ts_failed: List[str] = []
            for code in codes:
                try:
                    df = fetch_func(code, start_ymd, end_ymd)
                    if df is not None and not df.empty:
                        save_func(code, df, config=cfg)
                        ts_ok.append(code)
                    else:
                        ts_failed.append(code)
                except Exception:
                    ts_failed.append(code)
            if ts_ok:
                summary["steps"].append(
                    {
                        "tool": f"{kind_label}_historical_tushare",
                        "success": True,
                        "message": f"tushare_preferred_ok={len(ts_ok)} fallback_needed={len(ts_failed)}",
                        "codes_tushare_ok": ts_ok,
                        "codes_fallback": ts_failed,
                    }
                )
            return ts_ok, ts_failed

        if u["index_codes"]:
            _, idx_fallback = _prefer_tushare_daily(
                u["index_codes"],
                fetch_index_daily_tushare,
                save_index_daily_cache,
                "index",
            )
            if idx_fallback:
                r = tool_fetch_index_historical(
                    index_code=",".join(idx_fallback),
                    period="daily",
                    start_date=start,
                    end_date=end,
                    use_cache=True,
                )
                summary["steps"].append(
                    {
                        "tool": "index_historical_fallback",
                        "success": r.get("success"),
                        "message": r.get("message"),
                    }
                )
        if u["etf_codes"]:
            _, etf_fallback = _prefer_tushare_daily(
                u["etf_codes"],
                fetch_etf_daily_tushare,
                save_etf_daily_cache,
                "etf",
            )
            if etf_fallback:
                r = tool_fetch_etf_historical(
                    etf_code=",".join(etf_fallback),
                    period="daily",
                    start_date=start,
                    end_date=end,
                    use_cache=True,
                )
                summary["steps"].append(
                    {
                        "tool": "etf_historical_fallback",
                        "success": r.get("success"),
                        "message": r.get("message"),
                    }
                )
        if u["stock_codes"]:
            _, stock_fallback = _prefer_tushare_daily(
                u["stock_codes"],
                fetch_stock_daily_tushare,
                save_stock_daily_cache,
                "stock",
            )
            if stock_fallback:
                r = tool_fetch_stock_historical(
                    stock_code=",".join(stock_fallback),
                    period="daily",
                    start_date=start,
                    end_date=end,
                    use_cache=True,
                )
                summary["steps"].append(
                    {
                        "tool": "stock_historical_fallback",
                        "success": r.get("success"),
                        "message": r.get("message"),
                    }
                )

    if phase == "morning_daily":
        _run_daily_historical_block()

    elif phase in ("intraday_minute", "close_minute"):
        from plugins.data_collection.index.fetch_minute import tool_fetch_index_minute
        from plugins.data_collection.etf.fetch_minute import tool_fetch_etf_minute
        from plugins.data_collection.stock.fetch_minute import tool_fetch_stock_minute

        tz = pytz.timezone("Asia/Shanghai")
        if now is not None:
            if now.tzinfo is None:
                now_sh = tz.localize(now)
            else:
                now_sh = now.astimezone(tz)
        else:
            now_sh = datetime.now(tz)
        minute = now_sh.minute

        if u["index_codes"]:
            r = tool_fetch_index_minute(
                index_code=",".join(u["index_codes"]),
                period="5,15,30",
                use_cache=True,
            )
            summary["steps"].append(
                {"tool": "index_minute", "success": r.get("success"), "message": r.get("message")}
            )
        if u["etf_codes"]:
            r = tool_fetch_etf_minute(
                etf_code=",".join(u["etf_codes"]),
                period="5,15,30",
                use_cache=True,
            )
            summary["steps"].append(
                {"tool": "etf_minute", "success": r.get("success"), "message": r.get("message")}
            )

        do_stock = bool(u["stock_codes"])
        if phase == "intraday_minute" and throttle_stock:
            do_stock = do_stock and minute in (1, 31)
        if do_stock:
            r = tool_fetch_stock_minute(
                stock_code=",".join(u["stock_codes"]),
                period="5,15,30",
                use_cache=True,
            )
            summary["steps"].append(
                {"tool": "stock_minute", "success": r.get("success"), "message": r.get("message")}
            )
        elif u["stock_codes"]:
            summary["steps"].append({"tool": "stock_minute", "skipped": True, "reason": "throttle_stock"})

        if phase == "close_minute":
            summary["steps"].append(
                {"tool": "daily_historical_after_close", "note": "etf/index/stock daily refresh"}
            )
            _run_daily_historical_block()

    return summary


def format_summary_for_feishu(summary: Dict[str, Any], *, collection_ok: bool) -> Tuple[str, str]:
    """生成飞书 title 与正文（含各 step 摘要）。"""
    phase = summary.get("phase", "")
    title = f"data_cache 采集 {phase}"
    lines: List[str] = [f"phase={phase}", f"collection_success={collection_ok}"]
    for step in summary.get("steps", []):
        if not isinstance(step, dict):
            continue
        tool = step.get("tool", "?")
        if step.get("skipped"):
            lines.append(f"- {tool}: skipped ({step.get('reason', '')})")
            continue
        if "note" in step and "success" not in step:
            lines.append(f"- {tool}: {step.get('note', '')}")
            continue
        ok = step.get("success")
        msg = step.get("message") or ""
        lines.append(f"- {tool}: success={ok} {msg}".strip())
    body = "\n".join(lines)
    if not collection_ok:
        body += "\n\n(降级通知：采集存在失败步骤，请检查日志与数据源。)"
    return title, body


def summary_to_json_line(summary: Dict[str, Any]) -> str:
    """与 CLI 一致的单行 JSON（ensure_ascii=False 由调用方 print）。"""
    return json.dumps(summary, ensure_ascii=False)
