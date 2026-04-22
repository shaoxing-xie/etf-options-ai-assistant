"""只读读取震荡市选股相关 JSON/YAML（Chart Console API）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.data_layer import MetaEnvelope, write_contract_json

_DATE_KEY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

# 与四工具/定调对齐的可选字段：weekly_calibration、data/screening/sentiment_context.json、
# data/sentiment_check/YYYY-MM-DD.json（pre-market 侧车）
_SENTIMENT_KEYS = (
    "overall_score",
    "sentiment_stage",
    "sentiment_dispersion",
    "market_sentiment_score",
    "sentiment_notes",
    "data_completeness_ratio",
    "action_bias",
    "confidence_band",
    "degraded",
    "factor_attribution",
    "precheck_date",
)


def validate_screening_date_key(date_str: str) -> bool:
    s = (date_str or "").strip()
    if not _DATE_KEY.match(s):
        return False
    y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    if m < 1 or m > 12 or d < 1 or d > 31:
        return False
    return True


def screening_artifact_path(screening_dir: Path, date_key: str) -> Path | None:
    if not validate_screening_date_key(date_key):
        return None
    p = (screening_dir / f"{date_key}.json").resolve()
    try:
        screening_dir_resolved = screening_dir.resolve()
        if not str(p).startswith(str(screening_dir_resolved)):
            return None
    except OSError:
        return None
    return p


def list_screening_date_files(screening_dir: Path) -> list[str]:
    """返回 YYYY-MM-DD 日期键列表（升序）。"""
    if not screening_dir.is_dir():
        return []
    out: list[str] = []
    for p in screening_dir.iterdir():
        if not p.is_file() or p.suffix.lower() != ".json":
            continue
        stem = p.stem
        if stem == "emergency_pause":
            continue
        if validate_screening_date_key(stem):
            out.append(stem)
    out.sort()
    return out


def read_json_optional(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pick_sentiment_fields(src: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in _SENTIMENT_KEYS:
        if k in src and src[k] is not None:
            out[k] = src[k]
    return out


def read_sentiment_context_file(screening_dir: Path) -> dict[str, Any]:
    """可选落盘：`data/screening/sentiment_context.json`（与极端情绪巡检同源时可由工作流写入）。"""
    p = screening_dir / "sentiment_context.json"
    j = read_json_optional(p)
    return j if isinstance(j, dict) else {}


def list_sentiment_check_date_files(sentiment_check_dir: Path) -> list[str]:
    """`data/sentiment_check/` 下 YYYY-MM-DD.json（09:10 情绪前置检查侧车）日期键，升序。"""
    if not sentiment_check_dir.is_dir():
        return []
    out: list[str] = []
    for p in sentiment_check_dir.iterdir():
        if not p.is_file() or p.suffix.lower() != ".json":
            continue
        stem = p.stem
        if validate_screening_date_key(stem):
            out.append(stem)
    out.sort()
    return out


def read_latest_sentiment_precheck(root: Path) -> dict[str, Any]:
    """读取最新 `data/sentiment_check/YYYY-MM-DD.json`，并注入 `precheck_date`（文件名日期）。"""
    d = root / "data" / "sentiment_check"
    dates = list_sentiment_check_date_files(d)
    if not dates:
        return {}
    last = dates[-1]
    j = read_json_optional(d / f"{last}.json")
    if not isinstance(j, dict):
        return {}
    out = dict(j)
    out["precheck_date"] = last
    return out


def _sentiment_note(
    wc: dict[str, Any],
    side: dict[str, Any],
    precheck: dict[str, Any],
    merged_nonempty: bool,
) -> str:
    if not merged_nonempty:
        return (
            "字段来自 config/weekly_calibration.json、data/screening/sentiment_context.json "
            "与/或 data/sentiment_check/YYYY-MM-DD.json（OpenClaw `pre-market-sentiment-check` 侧车）；"
            "三者均未落盘时为空。"
        )
    parts: list[str] = []
    if _pick_sentiment_fields(wc):
        parts.append("config/weekly_calibration.json")
    if _pick_sentiment_fields(side):
        parts.append("data/screening/sentiment_context.json")
    prec_pick = _pick_sentiment_fields(precheck)
    if prec_pick:
        pd = str(precheck.get("precheck_date") or "").strip()
        if pd:
            parts.append(f"data/sentiment_check/{pd}.json（09:10 情绪前置检查）")
        else:
            parts.append("data/sentiment_check/（09:10 情绪前置检查）")
    return "字段来自 " + "、".join(parts) + "。"


def build_sentiment_snapshot(
    weekly_cal: dict[str, Any] | None,
    screening_dir: Path,
    root: Path,
) -> dict[str, Any]:
    wc = weekly_cal or {}
    side = read_sentiment_context_file(screening_dir)
    precheck = read_latest_sentiment_precheck(root)
    merged = {**_pick_sentiment_fields(wc), **_pick_sentiment_fields(side)}
    prec_pick = _pick_sentiment_fields(precheck)
    for k, v in prec_pick.items():
        if k not in merged or merged[k] is None:
            merged[k] = v
    merged["note"] = _sentiment_note(wc, side, precheck, bool(merged))
    return merged


def persist_dashboard_snapshot(root: Path, payload: dict[str, Any], trade_date: str) -> None:
    run_id = f"chart_console_{trade_date.replace('-', '')}"
    write_contract_json(
        root / "data" / "semantic" / "dashboard_snapshot" / f"{trade_date}.json",
        payload=payload,
        meta=MetaEnvelope(
            schema_name="sentiment_snapshot_v1",
            schema_version="1.0.0",
            task_id="pre-market-sentiment-check",
            run_id=run_id,
            data_layer="L4",
            trade_date=trade_date,
            quality_status="degraded" if bool(payload.get("degraded")) else "ok",
            lineage_refs=[str(root / "data" / "sentiment_check"), str(root / "config" / "weekly_calibration.json")],
            source_tools=["screening_reader.build_sentiment_snapshot"],
        ),
    )


def read_weekly_review_file(screening_dir: Path) -> dict[str, Any] | None:
    """周度复盘结构化结果：`data/screening/weekly_review.json`（由复盘任务或手工合并后放置）。"""
    p = screening_dir / "weekly_review.json"
    j = read_json_optional(p)
    return j if isinstance(j, dict) else None


def read_screening_policy_section(root: Path) -> dict[str, Any]:
    p = root / "config" / "data_quality_policy.yaml"
    if not p.is_file():
        return {}
    try:
        import yaml

        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        sec = doc.get("screening")
        return sec if isinstance(sec, dict) else {}
    except Exception:
        # Lightweight fallback parser for environments without PyYAML.
        text = p.read_text(encoding="utf-8")
        out: dict[str, Any] = {}
        in_screening = False
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line.strip():
                continue
            if line.startswith("screening:"):
                in_screening = True
                continue
            if in_screening:
                if not line.startswith("  "):
                    break
                seg = line.strip()
                if ":" not in seg:
                    continue
                k, v = seg.split(":", 1)
                v = v.strip()
                if v.isdigit():
                    out[k.strip()] = int(v)
                else:
                    try:
                        out[k.strip()] = float(v)
                    except ValueError:
                        out[k.strip()] = v
        return out


class ScreeningReader:
    """项目根目录下的 screening / watchlist / 定调只读聚合。"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @property
    def screening_dir(self) -> Path:
        return self.root / "data" / "screening"

    @property
    def watchlist_path(self) -> Path:
        return self.root / "data" / "watchlist" / "default.json"

    @property
    def weekly_calibration_path(self) -> Path:
        return self.root / "config" / "weekly_calibration.json"

    def read_watchlist(self) -> dict[str, Any]:
        w = read_json_optional(self.watchlist_path)
        if not isinstance(w, dict):
            return {"version": 1, "updated_at": None, "symbols": [], "meta": {}}
        w.setdefault("version", 1)
        w.setdefault("symbols", [])
        w.setdefault("meta", {})
        return w

    def read_weekly_calibration(self) -> dict[str, Any] | None:
        j = read_json_optional(self.weekly_calibration_path)
        return j if isinstance(j, dict) else None

    def read_emergency_pause(self) -> dict[str, Any] | None:
        p = self.screening_dir / "emergency_pause.json"
        j = read_json_optional(p)
        return j if isinstance(j, dict) else None

    def read_artifact_by_date(self, date_key: str) -> dict[str, Any] | None:
        path = screening_artifact_path(self.screening_dir, date_key)
        if path is None:
            return None
        j = read_json_optional(path)
        return j if isinstance(j, dict) else None

    def latest_artifact(self) -> tuple[str | None, dict[str, Any] | None]:
        dates = list_screening_date_files(self.screening_dir)
        if not dates:
            return None, None
        last = dates[-1]
        art = self.read_artifact_by_date(last)
        return last, art

    def effective_pause(self) -> dict[str, Any]:
        try:
            from src.screening_quality_gate import screening_should_skip_due_to_pause

            blocked, reason = screening_should_skip_due_to_pause()
        except Exception:
            blocked, reason = (False, "")
        wc = self.read_weekly_calibration() or {}
        regime = str(wc.get("regime") or "").strip().lower()
        weekly_pause = regime == "pause"
        ep = self.read_emergency_pause() or {}
        emergency_active = bool(ep.get("active"))
        return {
            "blocked": blocked,
            "reason": reason or None,
            "weekly_regime_pause": weekly_pause,
            "emergency_pause_active": emergency_active,
        }

    def aggregate_recent(self, n: int = 20) -> dict[str, Any]:
        dates = list_screening_date_files(self.screening_dir)
        tail = dates[-max(1, n) :] if dates else []
        merged_count = 0
        qs_series: list[dict[str, Any]] = []
        pause_runs = 0
        for dk in tail:
            art = self.read_artifact_by_date(dk)
            if not art:
                continue
            if art.get("pause_active"):
                pause_runs += 1
            if art.get("merged_watchlist_path"):
                merged_count += 1
            scr = art.get("screening")
            if isinstance(scr, dict):
                qs = scr.get("quality_score")
                qs_series.append({"date": dk, "quality_score": qs})
        return {
            "window_dates": len(tail),
            "runs_with_watchlist_merged": merged_count,
            "runs_with_pause_active": pause_runs,
            "quality_score_series": qs_series,
            "note": "精确绩效依赖周度复盘产出；此处为 screening 审计文件聚合。",
        }

    def run_snapshot(self, art: dict[str, Any] | None) -> dict[str, Any]:
        """当前审计文件上的「策略运行摘要」（与插件契约 quality_score / degraded / config_hash 对齐）。"""
        if not art:
            return {}
        scr = art.get("screening")
        scr = scr if isinstance(scr, dict) else {}
        return {
            "artifact_run_date": art.get("run_date"),
            "artifact_written_at": art.get("written_at"),
            "watchlist_merged": bool(art.get("merged_watchlist_path")),
            "schema_ok": art.get("schema_ok"),
            "schema_issues": art.get("schema_issues"),
            "pause_active_artifact": art.get("pause_active"),
            "watchlist_allowed": art.get("watchlist_allowed"),
            "screening_success": scr.get("success"),
            "quality_score": scr.get("quality_score"),
            "degraded": scr.get("degraded"),
            "config_hash": scr.get("config_hash"),
            "plugin_version": scr.get("plugin_version"),
            "universe": scr.get("universe"),
            "regime_hint": scr.get("regime_hint"),
            "elapsed_ms": scr.get("elapsed_ms"),
        }

    def summary(self) -> dict[str, Any]:
        wc = self.read_weekly_calibration()
        ep = self.read_emergency_pause()
        eff = self.effective_pause()
        wl = self.read_watchlist()
        policy = read_screening_policy_section(self.root)
        latest_date, latest_art = self.latest_artifact()
        latest_rows: list[dict[str, Any]] = []
        latest_screening: dict[str, Any] | None = None
        if latest_art:
            scr = latest_art.get("screening")
            if isinstance(scr, dict):
                latest_screening = scr
                data = scr.get("data")
                if isinstance(data, list):
                    latest_rows = [x for x in data if isinstance(x, dict)]
        agg = self.aggregate_recent(20)
        sentiment_snapshot = build_sentiment_snapshot(wc, self.screening_dir, self.root)
        try:
            td = latest_date or str(sentiment_snapshot.get("precheck_date") or "")
            if validate_screening_date_key(td):
                persist_dashboard_snapshot(self.root, sentiment_snapshot, td)
        except Exception:
            pass
        weekly_review = read_weekly_review_file(self.screening_dir)
        run_snap = self.run_snapshot(latest_art)
        return {
            "weekly_calibration": wc,
            "emergency_pause": ep,
            "effective_pause": eff,
            "screening_policy": policy,
            "watchlist": wl,
            "latest_screening_date": latest_date,
            "latest_artifact": latest_art,
            "latest_screening": latest_screening,
            "latest_screening_rows": latest_rows,
            "aggregate": agg,
            "sentiment_snapshot": sentiment_snapshot,
            "weekly_review": weekly_review,
            "run_snapshot": run_snap,
        }

    def history(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for dk in list_screening_date_files(self.screening_dir):
            art = self.read_artifact_by_date(dk)
            out.append(
                {
                    "date": dk,
                    "pause_active": bool(art.get("pause_active")) if art else False,
                    "watchlist_merged": bool(art.get("merged_watchlist_path")) if art else False,
                    "run_date": art.get("run_date") if art else dk,
                    "written_at": art.get("written_at") if art else None,
                }
            )
        return out
