"""只读读取尾盘选股落盘（data/tail_screening）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_DATE_KEY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _valid_date_key(s: str) -> bool:
    t = (s or "").strip()
    if not _DATE_KEY.match(t):
        return False
    y, m, d = int(t[0:4]), int(t[5:7]), int(t[8:10])
    if y < 2000 or m < 1 or m > 12 or d < 1 or d > 31:
        return False
    return True


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
        return j if isinstance(j, dict) else None
    except Exception:
        return None


class TailScreeningReader:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @property
    def data_dir(self) -> Path:
        return self.root / "data" / "tail_screening"

    def list_dates(self) -> list[str]:
        d = self.data_dir
        if not d.is_dir():
            return []
        out: list[str] = []
        for p in d.iterdir():
            if not p.is_file() or p.suffix.lower() != ".json":
                continue
            if p.stem == "latest":
                continue
            if _valid_date_key(p.stem):
                out.append(p.stem)
        out.sort()
        return out

    def read_latest(self) -> dict[str, Any] | None:
        return _read_json(self.data_dir / "latest.json")

    def read_by_date(self, date_key: str) -> dict[str, Any] | None:
        if not _valid_date_key(date_key):
            return None
        return _read_json(self.data_dir / f"{date_key}.json")

    def summary(self) -> dict[str, Any]:
        latest = self.read_latest()
        dates = self.list_dates()
        return {
            "latest": latest,
            "history_dates": dates,
            "latest_date": (latest or {}).get("run_date") if isinstance(latest, dict) else None,
        }

    def history(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for d in self.list_dates():
            j = self.read_by_date(d) or {}
            summ = j.get("summary", {}) if isinstance(j, dict) else {}
            out.append(
                {
                    "date": d,
                    "stage": j.get("stage"),
                    "generated_at": j.get("generated_at"),
                    "recommended_count": summ.get("recommended_count", 0),
                }
            )
        return out
