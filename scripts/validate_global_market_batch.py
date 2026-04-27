#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'").strip('"')
        if k and k not in os.environ:
            os.environ[k] = v


def _load_cfg(cfg_path: Path) -> dict[str, Any]:
    if not cfg_path.is_file():
        return {}
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _chunk(items: list[str], n: int) -> list[list[str]]:
    n = max(1, int(n))
    return [items[i : i + n] for i in range(0, len(items), n)]


@dataclass
class BatchResult:
    source: str
    chunk_size: int
    delay_sec: float
    elapsed_sec: float
    success_symbols: int
    total_symbols: int
    failures: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "chunk_size": self.chunk_size,
            "delay_sec": self.delay_sec,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "success_symbols": self.success_symbols,
            "total_symbols": self.total_symbols,
            "success_rate": round(self.success_symbols / self.total_symbols, 4) if self.total_symbols else 0.0,
            "failures": self.failures,
        }


def run_yfinance(
    symbols: list[str],
    cfg: dict[str, Any],
    chunk_size: int,
    delay_sec: float,
    runs: int,
) -> list[BatchResult]:
    from plugins.data_collection.index.fetch_global import _fetch_yfinance

    out: list[BatchResult] = []
    for _ in range(runs):
        t0 = time.time()
        success: set[str] = set()
        failures: dict[str, str] = {}
        for batch in _chunk(symbols, chunk_size):
            res = _fetch_yfinance(batch, cfg)
            got = {str(x.get("code")) for x in (res.get("data") or []) if isinstance(x, dict) and x.get("code")}
            for s in batch:
                if s in got:
                    success.add(s)
                else:
                    failures[s] = str(res.get("message") or "missing_in_batch")
            if delay_sec > 0:
                time.sleep(delay_sec)
        out.append(
            BatchResult(
                source="yfinance",
                chunk_size=chunk_size,
                delay_sec=delay_sec,
                elapsed_sec=time.time() - t0,
                success_symbols=len(success),
                total_symbols=len(symbols),
                failures=failures,
            )
        )
    return out


def run_fmp(
    symbols: list[str],
    cfg: dict[str, Any],
    chunk_size: int,
    delay_sec: float,
    runs: int,
) -> list[BatchResult]:
    from plugins.data_collection.index.fetch_global import _fetch_fmp, _resolve_fmp_api_keys

    fmp_cfg = (((cfg.get("data_sources") or {}).get("global_index") or {}).get("latest") or {}).get("fmp") or {}
    keys = _resolve_fmp_api_keys(fmp_cfg if isinstance(fmp_cfg, dict) else {})
    out: list[BatchResult] = []
    for _ in range(runs):
        t0 = time.time()
        success: set[str] = set()
        failures: dict[str, str] = {}
        for batch in _chunk(symbols, chunk_size):
            res = _fetch_fmp(batch, keys, cfg)
            got = {str(x.get("code")) for x in (res.get("data") or []) if isinstance(x, dict) and x.get("code")}
            msg = str(res.get("message") or "")
            for s in batch:
                if s in got:
                    success.add(s)
                else:
                    failures[s] = msg or "missing_in_batch"
            if delay_sec > 0:
                time.sleep(delay_sec)
        out.append(
            BatchResult(
                source="fmp",
                chunk_size=chunk_size,
                delay_sec=delay_sec,
                elapsed_sec=time.time() - t0,
                success_symbols=len(success),
                total_symbols=len(symbols),
                failures=failures,
            )
        )
    return out


def run_tool_global_spot(symbols: list[str], runs: int) -> list[BatchResult]:
    from plugins.data_collection.index.fetch_global import tool_fetch_global_index_spot

    out: list[BatchResult] = []
    payload = ",".join(symbols)
    for _ in range(runs):
        t0 = time.time()
        res = tool_fetch_global_index_spot(index_codes=payload)
        data = res.get("data") or []
        got = {str(x.get("code")) for x in data if isinstance(x, dict) and x.get("code")}
        failures = {s: str(res.get("message") or "missing_in_result") for s in symbols if s not in got}
        out.append(
            BatchResult(
                source="tool_fetch_global_index_spot",
                chunk_size=len(symbols),
                delay_sec=0.0,
                elapsed_sec=time.time() - t0,
                success_symbols=len(got),
                total_symbols=len(symbols),
                failures=failures,
            )
        )
    return out


def run_yfinance_futures(
    symbols: list[str],
    cfg: dict[str, Any],
    chunk_size: int,
    delay_sec: float,
    runs: int,
) -> list[BatchResult]:
    # Reuse plugin yfinance fetcher to avoid import path conflicts.
    from plugins.data_collection.index.fetch_global import _fetch_yfinance

    out: list[BatchResult] = []
    for _ in range(runs):
        t0 = time.time()
        success: set[str] = set()
        failures: dict[str, str] = {}
        for batch in _chunk(symbols, chunk_size):
            res = _fetch_yfinance(batch, cfg)
            got = {str(x.get("code")) for x in (res.get("data") or []) if isinstance(x, dict) and x.get("code")}
            msg = str(res.get("message") or "")
            for sym in batch:
                if sym in got:
                    success.add(sym)
                else:
                    failures[sym] = msg or "missing_in_batch"
            if delay_sec > 0:
                time.sleep(delay_sec)
        out.append(
            BatchResult(
                source="yfinance_futures",
                chunk_size=chunk_size,
                delay_sec=delay_sec,
                elapsed_sec=time.time() - t0,
                success_symbols=len(success),
                total_symbols=len(symbols),
                failures=failures,
            )
        )
    return out


def run_tool_a50(runs: int) -> list[BatchResult]:
    from plugins.data_collection.futures.fetch_a50 import tool_fetch_a50_data

    out: list[BatchResult] = []
    for _ in range(runs):
        t0 = time.time()
        failures: dict[str, str] = {}
        ok = 0
        try:
            raw = tool_fetch_a50_data(symbol="A50期指", data_type="spot", use_cache=True)
            spot = raw.get("spot_data") if isinstance(raw, dict) else None
            cp = spot.get("current_price") if isinstance(spot, dict) else None
            if cp is not None:
                ok = 1
            else:
                failures["A50"] = str((raw or {}).get("message") or "spot_data_missing")
        except Exception as e:
            failures["A50"] = repr(e)
        out.append(
            BatchResult(
                source="tool_fetch_a50_data",
                chunk_size=1,
                delay_sec=0.0,
                elapsed_sec=time.time() - t0,
                success_symbols=ok,
                total_symbols=1,
                failures=failures,
            )
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate global market batch pull behavior by source/chunk/delay.")
    parser.add_argument("--chunk-sizes", default="1,3,5,8", help="Comma-separated batch sizes.")
    parser.add_argument("--delays", default="0,0.5,1.0", help="Comma-separated per-batch sleep seconds.")
    parser.add_argument("--runs", type=int, default=1, help="Repeat count per setting.")
    parser.add_argument("--skip-fmp", action="store_true", help="Skip FMP tests.")
    parser.add_argument("--skip-tool", action="store_true", help="Skip tool_fetch_global_index_spot test.")
    parser.add_argument("--futures-mode", action="store_true", help="Run futures-focused matrix (NQ/ES/YM/NKD + A50 tool).")
    parser.add_argument("--output", default="", help="Optional output json path.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    _load_env_file(Path.home() / ".openclaw" / ".env")
    _load_env_file(root / ".env")
    cfg = _load_cfg(root / "config" / "domains" / "market_data.yaml")

    # Make plugin importable from development repo.
    dev_plugin = Path.home() / "openclaw-data-china-stock"
    if dev_plugin.is_dir() and str(dev_plugin) not in sys.path:
        sys.path.insert(0, str(dev_plugin))

    symbols = [
        "^HSI",
        "^HSCE",
        "^N225",
        "^KS11",
        "^AXJO",
        "^STI",
        "^BSESN",
        "^TWII",
        "^DJI",
        "^IXIC",
        "^GSPC",
        "^FTSE",
        "^GDAXI",
        "^FCHI",
        "^STOXX50E",
    ]
    chunk_sizes = [int(x.strip()) for x in str(args.chunk_sizes).split(",") if x.strip()]
    delays = [float(x.strip()) for x in str(args.delays).split(",") if x.strip()]

    report: dict[str, Any] = {
        "_meta": {
            "generated_at": _utc_now(),
            "script": "scripts/validate_global_market_batch.py",
            "symbols_count": len(symbols),
            "symbols": symbols,
            "runs": args.runs,
            "chunk_sizes": chunk_sizes,
            "delays": delays,
        },
        "results": [],
    }

    # yfinance matrix
    for c in chunk_sizes:
        for d in delays:
            report["results"].extend(x.as_dict() for x in run_yfinance(symbols, cfg, c, d, args.runs))

    # fmp matrix
    if not args.skip_fmp:
        for c in chunk_sizes:
            for d in delays:
                report["results"].extend(x.as_dict() for x in run_fmp(symbols, cfg, c, d, args.runs))

    if not args.skip_tool:
        report["results"].extend(x.as_dict() for x in run_tool_global_spot(symbols, args.runs))

    if args.futures_mode:
        fut_symbols = ["NQ=F", "ES=F", "YM=F", "NKD=F", "XINA50=F", "CN=F", "2823.HK"]
        report["_meta"]["futures_symbols"] = fut_symbols
        for c in chunk_sizes:
            for d in delays:
                report["results"].extend(x.as_dict() for x in run_yfinance_futures(fut_symbols, cfg, c, d, args.runs))
        report["results"].extend(x.as_dict() for x in run_tool_a50(args.runs))

    # Print concise summary sorted by success rate then elapsed.
    print("=== Validation Summary ===")
    rows = list(report["results"])
    rows.sort(key=lambda r: (-float(r.get("success_rate", 0.0)), float(r.get("elapsed_sec", 0.0))))
    for r in rows:
        print(
            f"{r['source']:>28} | chunk={r['chunk_size']:>2} delay={r['delay_sec']:<4} "
            f"| success={r['success_symbols']}/{r['total_symbols']} ({r['success_rate']:.2%}) "
            f"| elapsed={r['elapsed_sec']:.2f}s"
        )
    print("=== End Summary ===")

    out_path = Path(args.output).expanduser() if args.output else (root / "data" / "meta" / "evidence" / f"global_market_batch_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report_file={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

