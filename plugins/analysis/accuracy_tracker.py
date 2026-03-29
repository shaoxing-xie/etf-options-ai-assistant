"""
盘前预测落盘与昨日回顾（轻量）。完整校验依赖行情口径与 prediction_verification 对齐。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _records_dir() -> Path:
    d = _root() / "data" / "prediction_records"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _limitup_records_dir() -> Path:
    d = _root() / "data" / "limitup_research_records"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tool_record_before_open_prediction(
    report_data: Dict[str, Any],
    trade_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    将当日盘前报告中的波动/区间预测写入 prediction_records/{date}.json。
    trade_date: YYYYMMDD，默认上海当日。
    """
    tz = pytz.timezone("Asia/Shanghai")
    d = trade_date or datetime.now(tz).strftime("%Y%m%d")
    path = _records_dir() / f"{d}.json"
    payload = {
        "trade_date": d,
        "saved_at": datetime.now(tz).isoformat(),
        "report_type": report_data.get("report_type"),
        "volatility": report_data.get("volatility"),
        "intraday_range": report_data.get("intraday_range"),
        "overall_trend": report_data.get("overall_trend"),
    }
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return {"success": True, "message": "ok", "data": {"path": str(path)}}
    except Exception as e:
        return {"success": False, "message": str(e), "data": None}


def tool_get_yesterday_prediction_review(
    *,
    underlying_close: Optional[float] = None,
) -> Dict[str, Any]:
    """
    读取上一交易日 prediction_records，与 optional 收盘价对比（粗检）。
    underlying_close: 若提供则与昨日 intraday_range 上下界做是否落入区间判断。
    """
    tz = pytz.timezone("Asia/Shanghai")
    today = datetime.now(tz).date()
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    prev_s = prev.strftime("%Y%m%d")
    path = _records_dir() / f"{prev_s}.json"
    if not path.exists():
        return {
            "success": True,
            "message": "no_yesterday_record",
            "data": {"review": None},
        }
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"success": False, "message": str(e), "data": None}

    review: Dict[str, Any] = {
        "record_date": prev_s,
        "record": rec,
        "in_range": None,
    }
    ir = rec.get("intraday_range")
    if underlying_close is not None and isinstance(ir, dict):
        lo = ir.get("lower") or ir.get("low")
        hi = ir.get("upper") or ir.get("high")
        try:
            c = float(underlying_close)
            if lo is not None and hi is not None:
                lo_f, hi_f = float(lo), float(hi)
                review["in_range"] = lo_f <= c <= hi_f
        except Exception:
            pass

    return {"success": True, "message": "ok", "data": {"review": review}}


def tool_record_limitup_watch_outcome(
    *,
    trade_date: Optional[str] = None,
    leaders: Optional[List[str]] = None,
    watchlist_summary: Optional[str] = None,
    sector_notes: Optional[str] = None,
    hypothesis: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    涨停回马枪观察落盘：data/limitup_research_records/YYYYMMDD.json
    trade_date: YYYYMMDD，默认上海当日。
    """
    tz = pytz.timezone("Asia/Shanghai")
    d = trade_date or datetime.now(tz).strftime("%Y%m%d")
    path = _limitup_records_dir() / f"{d}.json"
    payload: Dict[str, Any] = {
        "trade_date": d,
        "saved_at": datetime.now(tz).isoformat(),
        "leaders": leaders or [],
        "watchlist_summary": (watchlist_summary or "").strip() or None,
        "sector_notes": (sector_notes or "").strip() or None,
        "hypothesis": (hypothesis or "").strip() or None,
    }
    if isinstance(extra, dict) and extra:
        payload["extra"] = extra
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"success": True, "message": "ok", "data": {"path": str(path)}}
    except Exception as e:
        return {"success": False, "message": str(e), "data": None}
