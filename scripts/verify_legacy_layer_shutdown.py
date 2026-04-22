#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _recent_files(directory: Path, within_minutes: int = 60) -> list[str]:
    if not directory.is_dir():
        return []
    threshold = datetime.now(timezone.utc) - timedelta(minutes=within_minutes)
    out: list[str] = []
    for p in directory.glob("*.json"):
        try:
            mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except Exception:
            continue
        if mt >= threshold:
            out.append(str(p))
    return sorted(out)


def _files_since(directory: Path, since_ts: datetime) -> list[str]:
    if not directory.is_dir():
        return []
    out: list[str] = []
    for p in directory.glob("*.json"):
        try:
            mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except Exception:
            continue
        if mt >= since_ts:
            out.append(str(p))
    return sorted(out)


def _single_file_since(path: Path, since_ts: datetime) -> list[str]:
    if not path.is_file():
        return []
    try:
        mt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except Exception:
        return []
    return [str(path)] if mt >= since_ts else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--paths",
        nargs="*",
        default=["data/screening", "data/tail_screening", "data/watchlist", "data/sentiment_check"],
        help="Legacy relative directories to verify.",
    )
    ap.add_argument("--within-minutes", type=int, default=180, help="Recent-write window.")
    ap.add_argument("--since", default="", help="ISO UTC timestamp; verify writes since this point.")
    ap.add_argument("--report-path", default="", help="Optional JSON report output path.")
    ap.add_argument("--files", nargs="*", default=[], help="Optional relative files to verify.")
    args = ap.parse_args()

    legacy_dirs = [ROOT / p for p in args.paths]
    since_ts = None
    if args.since:
        try:
            since_ts = datetime.strptime(args.since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            since_ts = None
    if since_ts is not None:
        findings = {str(d): _files_since(d, since_ts=since_ts) for d in legacy_dirs}
    else:
        findings = {str(d): _recent_files(d, within_minutes=max(1, int(args.within_minutes))) for d in legacy_dirs}
    single_files = [ROOT / p for p in args.files]
    if since_ts is not None:
        for f in single_files:
            findings[str(f)] = _single_file_since(f, since_ts=since_ts)
    else:
        for f in single_files:
            findings[str(f)] = _single_file_since(
                f, since_ts=datetime.now(timezone.utc) - timedelta(minutes=max(1, int(args.within_minutes)))
            )
    still_writing = any(findings[str(d)] for d in legacy_dirs)
    result = {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "still_writing": still_writing,
        "within_minutes": max(1, int(args.within_minutes)),
        "since": args.since or None,
        "paths": [str(d) for d in legacy_dirs],
        "files": [str(f) for f in single_files],
        "findings": findings,
    }
    if args.report_path:
        rp = Path(args.report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if still_writing else 0


if __name__ == "__main__":
    raise SystemExit(main())
