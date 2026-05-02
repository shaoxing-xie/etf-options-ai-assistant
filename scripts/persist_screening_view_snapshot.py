#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.chart_console.api.semantic_reader import SemanticReader
from apps.chart_console.api.screening_reader import validate_screening_date_key
from src.data_layer import MetaEnvelope, write_contract_json
from src.stock_code_map_cache import (
    resolve_stock_names_cached,
    load_sector_static_layers,
    write_back_sector_cache,
)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _default_trade_date() -> str:
    """
    Default semantic trade_date for local Chart Console:
    - Prefer explicit env override (useful for orchestration / manual reruns)
    - Else use Asia/Shanghai local calendar day (A-share primary schedule)
    - Fall back to UTC if tzdata is missing (rare, but keep running)
    """
    env = (os.environ.get("CHART_CONSOLE_TRADE_DATE") or os.environ.get("TRADE_DATE") or "").strip()
    if env:
        return env
    try:
        return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    except Exception:
        return _today_utc()


def _read_json_object(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _infer_trade_date_from_tail_artifacts() -> str | None:
    """
    If tail_screening wrote `latest.json` / `YYYY-MM-DD.json` with a run_date,
    treat that as the authoritative screening day for the snapshot.
    """
    tail_dir = ROOT / "data" / "tail_screening"
    latest = tail_dir / "latest.json"
    candidates = [latest] + sorted(tail_dir.glob("2*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    for p in candidates:
        if not p.is_file():
            continue
        obj = _read_json_object(p)
        rd = str(obj.get("run_date") or obj.get("runDate") or "").strip()
        if validate_screening_date_key(rd):
            return rd
    return None

def _looks_like_code(value: object) -> bool:
    s = str(value or "").strip()
    return len(s) == 6 and s.isdigit()


def _sector_from_row(row: dict) -> str:
    for k in (
        "industry",
        "所属行业",
        "行业",
        "sector_name",
        "板块",
        "板块名称",
        "concept_sector",
        "细分行业",
        "industry_name",
    ):
        v = row.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s and not _looks_like_code(s):
            return s
    return ""


def _fetch_sector_map(symbols: list[str]) -> dict[str, str]:
    codes = sorted({s for s in symbols if _looks_like_code(s)})
    if not codes:
        return {}
    runner = ROOT / "tool_runner.py"
    if not runner.is_file():
        return {}
    out: dict[str, str] = {}
    chunk_size = 35
    for i in range(0, len(codes), chunk_size):
        chunk = codes[i : i + chunk_size]
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "tool_fetch_stock_realtime",
                    json.dumps({"stock_code": ",".join(chunk), "mode": "production"}, ensure_ascii=False),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            res = json.loads((proc.stdout or "").strip() or "{}")
        except Exception:
            continue
        if not isinstance(res, dict) or not bool(res.get("success")):
            continue
        data = res.get("data")
        rows: list[dict] = []
        if isinstance(data, list):
            rows = [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            rows = [data]
        for row in rows:
            code = str(row.get("stock_code") or row.get("代码") or row.get("symbol") or "").strip()
            sec = _sector_from_row(row)
            if _looks_like_code(code) and sec:
                out[code] = sec
    return out


_TUSHARE_INDUSTRY_MAP: dict[str, str] | None = None


def _tushare_industry_cache_path() -> Path:
    return ROOT / "data" / "meta" / "cache" / "tushare_stock_basic_industry.json"


def _load_tushare_industry_map_full() -> dict[str, str]:
    """
    全市场 ts_code/symbol -> industry（Tushare stock_basic）。
    优先读磁盘缓存（默认 24h），避免每次 persist 都打全表接口。
    """
    global _TUSHARE_INDUSTRY_MAP
    if _TUSHARE_INDUSTRY_MAP is not None:
        return _TUSHARE_INDUSTRY_MAP
    cache_path = _tushare_industry_cache_path()
    ttl = int((os.environ.get("TUSHARE_INDUSTRY_CACHE_TTL_SEC") or "86400").strip() or "86400")
    out: dict[str, str] = {}
    try:
        if ttl > 0 and cache_path.is_file():
            age = time.time() - cache_path.stat().st_mtime
            if age < ttl:
                raw = json.loads(cache_path.read_text(encoding="utf-8") or "{}")
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        ks = str(k).strip().zfill(6)
                        vs = str(v).strip()
                        if _looks_like_code(ks) and vs and vs.lower() not in ("nan", "none"):
                            out[ks] = vs
    except Exception:
        out = {}
    if out:
        _TUSHARE_INDUSTRY_MAP = out
        return out
    try:
        from src.tushare_fallback import get_tushare_pro
    except Exception:
        _TUSHARE_INDUSTRY_MAP = {}
        return {}
    pro = get_tushare_pro()
    if pro is None:
        _TUSHARE_INDUSTRY_MAP = {}
        return {}
    try:
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name,industry")
    except Exception:
        _TUSHARE_INDUSTRY_MAP = {}
        return {}
    if df is None or not hasattr(df, "iterrows"):
        _TUSHARE_INDUSTRY_MAP = {}
        return {}
    for _, row in df.iterrows():
        sym = str(row.get("symbol") or "").strip().zfill(6)
        ind = row.get("industry")
        ind_s = str(ind).strip() if ind is not None else ""
        if not _looks_like_code(sym) or not ind_s or ind_s.lower() in ("nan", "none"):
            continue
        out[sym] = ind_s
    if out:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    _TUSHARE_INDUSTRY_MAP = out
    return out


def _fetch_sector_map_akshare(codes: list[str], *, max_codes: int = 60) -> dict[str, str]:
    """Deprecated: keep plugin-first discipline; no assistant-side direct source fallback."""
    return {}


def _fetch_sector_map_merged(symbols: list[str]) -> dict[str, str]:
    """行业/板块：data/meta/local 与 cache → Tushare stock_basic → 实时 tool → AkShare（易断）；不覆盖手工/缓存层已有值。"""
    codes = sorted({s for s in symbols if _looks_like_code(s)})
    if not codes:
        return {}
    merged: dict[str, str] = dict(load_sector_static_layers(ROOT, codes))
    ts_full = _load_tushare_industry_map_full()
    for c in codes:
        v = (ts_full.get(c) or "").strip()
        if v and not str(merged.get(c) or "").strip():
            merged[c] = v
    missing = [c for c in codes if not str(merged.get(c) or "").strip()]
    if missing:
        rt = _fetch_sector_map(missing)
        for k, v in rt.items():
            if v and not merged.get(k):
                merged[k] = v
    write_back_sector_cache(ROOT, merged, codes)
    return merged


def _fetch_name_map(symbols: list[str]) -> dict[str, str]:
    codes = [s for s in symbols if _looks_like_code(s)]
    if not codes:
        return {}
    runner = ROOT / "tool_runner.py"
    if not runner.is_file():
        return {}
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(runner),
                "tool_fetch_stock_realtime",
                json.dumps({"stock_code": ",".join(sorted(set(codes))), "mode": "production"}, ensure_ascii=False),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        res = json.loads((proc.stdout or "").strip() or "{}")
    except Exception:
        return {}
    if not isinstance(res, dict) or not bool(res.get("success")):
        return {}
    data = res.get("data")
    rows: list[dict] = []
    if isinstance(data, list):
        rows = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict):
        rows = [data]
    out: dict[str, str] = {}
    for row in rows:
        code = str(row.get("stock_code") or row.get("代码") or row.get("symbol") or "").strip()
        name = str(row.get("name") or row.get("股票简称") or row.get("证券简称") or row.get("display_name") or "").strip()
        if _looks_like_code(code) and name and not _looks_like_code(name):
            out[code] = name
    return out


def _apply_name_enrichment(payload: dict) -> None:
    data = payload.get("candidates") if isinstance(payload.get("candidates"), dict) else {}
    nightly = data.get("nightly") if isinstance(data.get("nightly"), list) else []
    tail = data.get("tail") if isinstance(data.get("tail"), list) else []
    pools = payload.get("tail_paradigm_pools") if isinstance(payload.get("tail_paradigm_pools"), dict) else {}
    symbols: list[str] = []
    for row in nightly + tail:
        if isinstance(row, dict):
            symbols.append(str(row.get("symbol") or "").strip())
    for rows in pools.values():
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    symbols.append(str(row.get("symbol") or "").strip())
    nmap = resolve_stock_names_cached(symbols, root=ROOT, fetch_missing=_fetch_name_map)
    if not nmap:
        return
    def fill(rows: list[dict]) -> None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            name = str(row.get("name") or "").strip()
            if _looks_like_code(sym) and (_looks_like_code(name) or not name) and nmap.get(sym):
                row["name"] = nmap[sym]
    fill(nightly)
    fill(tail)
    for rows in pools.values():
        if isinstance(rows, list):
            fill(rows)


def _apply_sector_enrichment(payload: dict) -> None:
    data = payload.get("candidates") if isinstance(payload.get("candidates"), dict) else {}
    nightly = data.get("nightly") if isinstance(data.get("nightly"), list) else []
    tail = data.get("tail") if isinstance(data.get("tail"), list) else []
    pools = payload.get("tail_paradigm_pools") if isinstance(payload.get("tail_paradigm_pools"), dict) else {}
    need: list[str] = []
    for row in nightly + tail:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip()
        if not sym or not _looks_like_code(sym):
            continue
        if not str(row.get("sector_name") or "").strip():
            need.append(sym)
    for rows in pools.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            if not sym or not _looks_like_code(sym):
                continue
            if not str(row.get("sector_name") or "").strip():
                need.append(sym)
    smap = _fetch_sector_map_merged(need)
    if not smap:
        return

    def fill_sec(rows: list[dict]) -> None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            if not str(row.get("sector_name") or "").strip() and smap.get(sym):
                row["sector_name"] = smap[sym]

    fill_sec(nightly)
    fill_sec(tail)
    for rows in pools.values():
        if isinstance(rows, list):
            fill_sec(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--trade-date",
        default="",
        help="YYYY-MM-DD; default: env CHART_CONSOLE_TRADE_DATE/TRADE_DATE, else Asia/Shanghai local date, else infer from data/tail_screening, else UTC today",
    )
    args = ap.parse_args()
    trade_date = (args.trade_date or "").strip() or _infer_trade_date_from_tail_artifacts() or _default_trade_date()
    if not validate_screening_date_key(trade_date):
        print(json.dumps({"success": False, "message": "invalid trade_date (use YYYY-MM-DD)"}, ensure_ascii=False))
        return 1
    reader = SemanticReader(ROOT)
    payload = reader.screening_view(trade_date, prefer_snapshot=False)
    _apply_name_enrichment(payload)
    _apply_sector_enrichment(payload)
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    out = ROOT / "data" / "semantic" / "screening_view" / f"{trade_date}.json"
    write_contract_json(
        out,
        payload=payload,
        meta=MetaEnvelope(
            schema_name="screening_view_v1",
            schema_version="1.0.0",
            task_id="intraday-tail-screening",
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
            data_layer="L4",
            trade_date=trade_date,
            quality_status=str(meta.get("quality_status") or "ok"),
            lineage_refs=[str(x) for x in (meta.get("lineage_refs") or [])],
            source_tools=["persist_screening_view_snapshot.py"],
        ),
    )
    print(json.dumps({"success": True, "path": str(out), "trade_date": trade_date}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
