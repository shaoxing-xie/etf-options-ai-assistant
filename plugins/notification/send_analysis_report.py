"""
发送分析类报告到钉钉自定义机器人（支持 SEC 加签）。

实现说明：
- **统一委托** `send_daily_report.tool_send_daily_report`，确保与「市场日报」共用同一套
  prod 门禁、字段归一化与钉钉投递逻辑。
- 历史上 `tool_runner` 曾将 `tool_send_daily_report` 别名到本函数并直接调 `_format_daily_report`，
  会**绕过** `tool_send_daily_report` 内的校验，已改为在 `tool_runner` 中注册真实 `tool_send_daily_report`。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from .send_daily_report import tool_send_daily_report


def _today_key(tz_name: str = "Asia/Shanghai") -> str:
    tz = ZoneInfo(tz_name)
    return datetime.now(tz).strftime("%Y-%m-%d")


def _memory_dir() -> Path:
    p = Path(os.environ.get("OPENCLAW_MEMORY_DIR", str(Path.home() / ".openclaw" / "memory")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _try_acquire_lock(lock_path: Path, *, stale_seconds: int = 7200) -> bool:
    """
    原子文件锁：仅用于生产环境的“同日只发送一次”。
    """
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        # 进程异常中断可能遗留锁文件；超过阈值视为陈旧锁并尝试清理一次
        try:
            st = lock_path.stat()
            age = max(0.0, datetime.now().timestamp() - st.st_mtime)
            if age >= float(stale_seconds):
                lock_path.unlink(missing_ok=True)
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return True
        except Exception:
            pass
        return False


def tool_send_analysis_report(
    report_data: Optional[Dict[str, Any]] = None,
    report_date: Optional[str] = None,
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
    mode: str = "prod",
    split_markdown_sections: bool = True,
    max_chars_per_message: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    工具：发送分析类报告到钉钉（自定义机器人 webhook）

    Args:
        report_data: 报告数据（结构同 tool_send_daily_report）
        report_date: 报告日期（可选）
        webhook_url: 可选：自定义机器人 webhook（包含 access_token）
        secret: 可选：SEC 安全模式密钥（用于 sign）
        keyword: 可选：关键词安全校验用（如果机器人启用关键词）
        mode: prod|test（test 不发网络请求）
        split_markdown_sections: 默认 True，与「每日市场分析报告」一致按章节分条；需单条推送时显式 False。
    """
    def _maybe_get_llm_summary(rd: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(rd, dict):
            return None
        for k in ("llm_summary", "analysis_summary", "summary"):
            v = rd.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # 兼容：可能存在 report_data 包壳（例如 { data: { report_data: {...}} }）
        for outer_k in ("data", "report_data"):
            outer = rd.get(outer_k)
            if not isinstance(outer, dict):
                continue
            for k in ("llm_summary", "analysis_summary", "summary"):
                v = outer.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            inner = outer.get("report_data")
            if isinstance(inner, dict):
                for k in ("llm_summary", "analysis_summary", "summary"):
                    v = inner.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
        return None

    # 如果 agent 没传 report_data，优先尝试从 last report 缓存回填（用于 etf_rotation_research 场景）
    if not isinstance(report_data, dict):
        try:
            date_key = _today_key()
            cache_p = _memory_dir() / f"etf_rotation_last_report_{date_key}.json"
            if cache_p.exists():
                cache_obj = json.loads(cache_p.read_text(encoding="utf-8"))
                rd = cache_obj.get("report_data")
                if isinstance(rd, dict):
                    report_data = rd
        except Exception:
            pass

    rt = None
    if isinstance(report_data, dict):
        rt = report_data.get("report_type")
        if not isinstance(rt, str) or not rt.strip():
            # 兼容：可能存在 report_data 包壳（例如 { data: { report_data: {...}} }）
            for outer_k in ("data", "report_data"):
                outer = report_data.get(outer_k)
                if isinstance(outer, dict) and isinstance(outer.get("report_type"), str):
                    rt = outer.get("report_type")
                    break

    # 兜底：如果是 etf_rotation_research 但缺少 llm_summary，发送工具自己回算，避免 N/A 退化
    if rt == "etf_rotation_research":
        has_llm = _maybe_get_llm_summary(report_data)
        if not has_llm:
            try:
                from analysis.etf_rotation_research import tool_etf_rotation_research

                etf_pool = kwargs.get("etf_pool") or kwargs.get("etal_pool") or ""
                lookback_days = kwargs.get("lookback_days", 120)
                top_k = kwargs.get("top_k", 3)
                config_path = kwargs.get("config_path")
                rotation_out = tool_etf_rotation_research(
                    etf_pool=etf_pool,
                    lookback_days=lookback_days,
                    top_k=top_k,
                    mode=mode,
                    config_path=config_path,
                )
                if isinstance(rotation_out, dict) and rotation_out.get("success"):
                    rd = (rotation_out.get("data") or {}).get("report_data")
                    if isinstance(rd, dict):
                        report_data = rd
                        rt = rd.get("report_type")
            except Exception:
                # 回算失败时交给下游：可能返回通用模板，但不会直接抛异常
                pass

    is_prod = str(mode).lower() == "prod"
    if is_prod and rt == "etf_rotation_research":
        date_key = _today_key()
        marker_path = _memory_dir() / f"etf_rotation_research_sent_{date_key}.json"
        lock_path = marker_path.with_suffix(marker_path.suffix + ".lock")

        # 已发送：直接跳过（但返回 success=True，让 VERIFY_SEND 视作“已满足发送条件”）
        if marker_path.exists():
            return {"success": True, "skipped": True, "message": f"duplicate send skipped: {date_key}"}

        if not _try_acquire_lock(lock_path):
            return {"success": True, "skipped": True, "message": f"duplicate send lock exists: {date_key}"}

        try:
            out = tool_send_daily_report(
                report_data=report_data,
                report_date=report_date,
                webhook_url=webhook_url,
                secret=secret,
                keyword=keyword,
                mode=mode,
                split_markdown_sections=split_markdown_sections,
                max_chars_per_message=max_chars_per_message,
                **kwargs,
            )
            if isinstance(out, dict) and out.get("success"):
                marker_path.write_text(
                    json.dumps({"sent_at": datetime.now().isoformat(), "date_key": date_key}, ensure_ascii=False),
                    encoding="utf-8",
                )
            return out
        finally:
            try:
                if lock_path.exists():
                    lock_path.unlink()
            except Exception:
                pass

    return tool_send_daily_report(
        report_data=report_data,
        report_date=report_date,
        webhook_url=webhook_url,
        secret=secret,
        keyword=keyword,
        mode=mode,
        split_markdown_sections=split_markdown_sections,
        max_chars_per_message=max_chars_per_message,
        **kwargs,
    )
