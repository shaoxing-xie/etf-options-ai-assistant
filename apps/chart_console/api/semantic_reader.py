from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.chart_console.api.screening_reader import ScreeningReader, validate_screening_date_key
from apps.chart_console.api.tail_screening_reader import TailScreeningReader


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return j if isinstance(j, dict) else None


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


class SemanticReader:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._screening = ScreeningReader(self.root)
        self._tail = TailScreeningReader(self.root)

    def _read_alert_thresholds(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "hit_rate_5d_pct": {"warn_below": 0.45, "bad_below": 0.35},
            "pause_events_count": {"warn_at_or_above": 2, "bad_at_or_above": 4},
            "tail_recommended_count": {"warn_at_or_below": 0},
        }
        cfg = _read_json(self.root / "config" / "research_alert_thresholds.json") or {}
        if not isinstance(cfg, dict):
            return defaults
        out = dict(defaults)
        for k, v in cfg.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                merged = dict(out[k])
                merged.update(v)
                out[k] = merged
            else:
                out[k] = v
        return out

    def _read_risk_gate_events(self, trade_date: str) -> list[dict[str, Any]]:
        """读取 L3 风控/巡检事件（migrated gate_events）并转换为 timeline 事件形态。"""
        out: list[dict[str, Any]] = []
        base = self.root / "data" / "decisions" / "risk" / "gate_events"
        if not base.is_dir():
            return out
        candidates = [
            base / f"{trade_date}.json",
            base / f"extreme_sentiment_{trade_date}.json",
        ]
        for p in candidates:
            j = _read_json(p)
            if not isinstance(j, dict):
                continue
            meta = j.get("_meta") if isinstance(j.get("_meta"), dict) else {}
            data = j.get("data") if isinstance(j.get("data"), dict) else {}
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
            event_time = payload.get("updated_at") or meta.get("generated_at") or f"{trade_date}T00:00:00Z"
            event_type = data.get("event_type") or "risk_gate_event"
            task_id = meta.get("task_id") or "unknown"
            summary = payload.get("reason") or event_type
            out.append(
                {
                    "event_id": f"{task_id}.{trade_date}",
                    "event_time": str(event_time),
                    "task_id": task_id,
                    "event_type": event_type,
                    "summary": str(summary),
                    "quality_status": meta.get("quality_status") or ("degraded" if payload.get("degraded") else "ok"),
                    "lineage_refs": meta.get("lineage_refs") or [],
                }
            )
        return out

    def _read_weekly_performance_context(self) -> dict[str, Any]:
        """优先读取 L3 周绩效（data/decisions/performance/weekly_*.json），否则返回空。"""
        base = self.root / "data" / "decisions" / "performance"
        if not base.is_dir():
            return {}
        # 约定：文件名 weekly_YYYY-WW.json，取最新字典序即可（与周序一致）。
        weekly = sorted([p for p in base.iterdir() if p.is_file() and p.name.startswith("weekly_") and p.suffix == ".json"])
        if not weekly:
            return {}
        j = _read_json(weekly[-1])
        if not isinstance(j, dict):
            return {}
        data = j.get("data") if isinstance(j.get("data"), dict) else {}
        meta = j.get("_meta") if isinstance(j.get("_meta"), dict) else {}
        if not data:
            return {}
        out = dict(data)
        out.setdefault("_meta", meta)
        return out

    def dashboard(self) -> dict[str, Any]:
        summary = self._screening.summary()
        trade_date_hint = str(summary.get("latest_screening_date") or "").strip()
        snap = self._read_sentiment_snapshot(trade_date_hint) or (summary.get("sentiment_snapshot") or {})
        wc = summary.get("weekly_calibration") or {}
        tail_latest = (self._tail.summary() or {}).get("latest") or {}
        recs = list((tail_latest.get("recommended") or [])[:5])
        # dashboard trade_date 代表“当前研究台主时间锚”，取已落盘信号里最新的交易日
        candidates = [
            str(summary.get("latest_screening_date") or "").strip(),
            str(snap.get("precheck_date") or "").strip(),
            str((tail_latest or {}).get("run_date") or "").strip(),
        ]
        trade_date = next((d for d in sorted([d for d in candidates if validate_screening_date_key(d)])[-1:]), "")
        # 风控/巡检事件：用于极端告警计数与门闸解释
        risk_events = self._read_risk_gate_events(str(trade_date or ""))
        extreme_payload = None
        emergency_payload = None
        for ev in risk_events:
            if ev.get("task_id") == "extreme-sentiment-monitor":
                extreme_payload = ev
            if ev.get("task_id") == "screening-emergency-stop":
                emergency_payload = ev
        # 极端告警：简单口径（score>=85 或 <=20 或阶段命中），否则 0；缺失为 None
        extreme_alert_count: int | None = None
        if extreme_payload is not None:
            extreme_alert_count = 0
            try:
                # event summary 不含结构化 score，这里依赖 screening.summary 里的 sentiment_snapshot
                sc = snap.get("overall_score")
                stage = str(snap.get("sentiment_stage") or "")
                if isinstance(sc, (int, float)) and (sc >= 85 or sc <= 20):
                    extreme_alert_count = 1
                elif stage and any(x in stage for x in ("冰点", "退潮", "极端")):
                    extreme_alert_count = 1
            except Exception:
                extreme_alert_count = 0
        latest_gate_reason = (summary.get("effective_pause") or {}).get("reason")
        if not latest_gate_reason and emergency_payload is not None:
            latest_gate_reason = emergency_payload.get("summary")

        payload = {
            "sentiment_temperature": {
                "score": snap.get("overall_score"),
                "stage": snap.get("sentiment_stage"),
                "dispersion": snap.get("sentiment_dispersion"),
                "trend": snap.get("action_bias"),
                "quality_status": {
                    "degraded": bool(snap.get("degraded")),
                    "score": snap.get("overall_score"),
                },
            },
            "market_state": {
                "regime": wc.get("regime"),
                "position_ceiling": wc.get("position_ceiling"),
                "pause_status": (summary.get("effective_pause") or {}).get("blocked"),
                "weekly_calibration_ref": "config/weekly_calibration.json",
            },
            "top_recommendations": recs,
            "risk_snapshot": {
                "emergency_pause": summary.get("emergency_pause"),
                "extreme_alert_count": extreme_alert_count,
                "latest_gate_reason": latest_gate_reason,
            },
            "_meta": {
                "schema_name": "dashboard_snapshot_v1",
                "schema_version": "1.0.0",
                "generated_at": snap.get("precheck_date") or "",
                "trade_date": trade_date,
            },
        }
        return payload

    def _read_semantic_snapshot(self, dataset: str, trade_date: str) -> dict[str, Any] | None:
        if not validate_screening_date_key(trade_date):
            return None
        path = self.root / "data" / "semantic" / dataset / f"{trade_date}.json"
        obj = _read_json(path)
        if not isinstance(obj, dict):
            return None
        data = obj.get("data") if isinstance(obj.get("data"), dict) else None
        meta = obj.get("_meta") if isinstance(obj.get("_meta"), dict) else None
        if not isinstance(data, dict):
            return None
        merged = dict(data)
        if isinstance(meta, dict):
            merged["_meta"] = meta
        return merged

    def _read_sentiment_snapshot(self, trade_date: str) -> dict[str, Any] | None:
        snap = self._read_semantic_snapshot("sentiment_snapshot", trade_date)
        if isinstance(snap, dict):
            return snap
        # backward compatibility path during cutover
        old = self._read_semantic_snapshot("dashboard_snapshot", trade_date)
        return old if isinstance(old, dict) else None

    def _resolve_trade_date(self, trade_date: str) -> str:
        td = (trade_date or "").strip()
        if validate_screening_date_key(td):
            return td
        dates = self.semantic_trade_dates()
        if dates:
            return dates[-1]
        dash = self.dashboard()
        dmeta = dash.get("_meta") if isinstance(dash.get("_meta"), dict) else {}
        d = str(dmeta.get("trade_date") or "").strip()
        if validate_screening_date_key(d):
            return d
        return _today_utc()

    def semantic_trade_dates(self) -> list[str]:
        base = self.root / "data" / "semantic" / "screening_view"
        if not base.is_dir():
            return []
        out = sorted([p.stem for p in base.glob("*.json") if p.is_file() and validate_screening_date_key(p.stem)])
        return out

    def timeline(self, trade_date: str) -> dict[str, Any]:
        if not validate_screening_date_key(trade_date):
            raise ValueError("invalid trade_date")
        events: list[dict[str, Any]] = []
        timeline_rows = _read_jsonl(self.root / "data" / "semantic" / "timeline_feed" / f"{trade_date}.jsonl")
        for row in timeline_rows:
            meta = row.get("_meta") if isinstance(row.get("_meta"), dict) else {}
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            events.append(
                {
                    "event_id": data.get("event_id"),
                    "event_time": data.get("event_time"),
                    "task_id": meta.get("task_id"),
                    "event_type": data.get("event_type"),
                    "summary": data.get("summary"),
                    "quality_status": meta.get("quality_status"),
                    "lineage_refs": meta.get("lineage_refs") or [],
                }
            )
        summary = self._screening.summary()
        sentiment = summary.get("sentiment_snapshot") or {}
        latest_art = summary.get("latest_artifact") or {}
        latest_tail = self._tail.read_by_date(trade_date) or self._tail.read_latest() or {}
        weekly_review = summary.get("weekly_review") or {}
        if sentiment:
            events.append(
                {
                    "event_id": f"pre-market-sentiment-check.{trade_date}",
                    "event_time": f"{trade_date}T00:10:00Z",
                    "task_id": "pre-market-sentiment-check",
                    "event_type": "sentiment_snapshot",
                    "summary": f"情绪分={sentiment.get('overall_score', '—')} 阶段={sentiment.get('sentiment_stage', '—')}",
                    "quality_status": "degraded" if sentiment.get("degraded") else "ok",
                    "lineage_refs": [],
                }
            )
        if isinstance(latest_art, dict) and latest_art.get("run_date") == trade_date:
            scr = latest_art.get("screening") if isinstance(latest_art.get("screening"), dict) else {}
            events.append(
                {
                    "event_id": f"nightly-stock-screening.{trade_date}",
                    "event_time": str(latest_art.get("written_at") or f"{trade_date}T12:00:00Z"),
                    "task_id": "nightly-stock-screening",
                    "event_type": "screening_audit",
                    "summary": f"候选={len(scr.get('data') or [])} 质量分={scr.get('quality_score', '—')}",
                    "quality_status": "degraded" if scr.get("degraded") else "ok",
                    "lineage_refs": [],
                }
            )
        if isinstance(latest_tail, dict) and latest_tail.get("run_date") == trade_date:
            tail_summary = latest_tail.get("summary") if isinstance(latest_tail.get("summary"), dict) else {}
            events.append(
                {
                    "event_id": f"intraday-tail-screening.{trade_date}",
                    "event_time": str(latest_tail.get("generated_at") or f"{trade_date}T14:30:00Z"),
                    "task_id": "intraday-tail-screening",
                    "event_type": "tail_recommendation",
                    "summary": f"推荐={tail_summary.get('recommended_count', 0)} 范式池非空={tail_summary.get('pools_nonempty_count', '—')}",
                    "quality_status": "degraded" if tail_summary.get("degraded_mode") else "ok",
                    "lineage_refs": [],
                }
            )
        if isinstance(weekly_review, dict) and weekly_review:
            events.append(
                {
                    "event_id": f"weekly-selection-review.{weekly_review.get('as_of', trade_date)}",
                    "event_time": str(weekly_review.get("as_of") or trade_date) + "T00:00:00Z",
                    "task_id": "weekly-selection-review",
                    "event_type": "weekly_review",
                    "summary": f"复盘区间={weekly_review.get('period_label', '—')}",
                    "quality_status": "ok",
                    "lineage_refs": ["data/screening/weekly_review.json"],
                }
            )
        # L3 风控/巡检事件补入 timeline（与任务结果对齐）
        events.extend(self._read_risk_gate_events(trade_date))
        return {
            "trade_date": trade_date,
            "events": events,
            "_meta": {
                "schema_name": "timeline_event_v1",
                "schema_version": "1.0.0",
                "generated_at": "",
                "trade_date": trade_date,
            },
        }

    def screening_candidates(self, trade_date: str) -> dict[str, Any]:
        if not validate_screening_date_key(trade_date):
            raise ValueError("invalid trade_date")
        snap = self._read_semantic_snapshot("screening_candidates", trade_date)
        if isinstance(snap, dict):
            return snap
        nightly = self._screening.read_artifact_by_date(trade_date) or {}
        screening = nightly.get("screening") if isinstance(nightly.get("screening"), dict) else {}
        return {
            "run_date": trade_date,
            "candidates": screening.get("data") if isinstance(screening.get("data"), list) else [],
            "summary": {
                "quality_score": screening.get("quality_score"),
                "degraded": screening.get("degraded"),
                "universe": screening.get("universe"),
            },
            "artifact_ref": str(self.root / "data" / "screening" / f"{trade_date}.json"),
            "_meta": {
                "schema_name": "screening_candidates_v1",
                "schema_version": "1.0.0",
                "task_id": "nightly-stock-screening",
                "run_id": "",
                "data_layer": "L4",
                "generated_at": "",
                "trade_date": trade_date,
                "quality_status": "degraded" if bool(screening.get("degraded")) else "ok",
                "lineage_refs": [str(self.root / "data" / "screening" / f"{trade_date}.json")],
            },
        }

    def screening_view(self, trade_date: str, *, prefer_snapshot: bool = True) -> dict[str, Any]:
        if not validate_screening_date_key(trade_date):
            raise ValueError("invalid trade_date")
        if prefer_snapshot:
            snap = self._read_semantic_snapshot("screening_view", trade_date)
            if isinstance(snap, dict):
                return snap
        nightly = self._screening.read_artifact_by_date(trade_date) or {}
        tail = self._tail.read_by_date(trade_date) or self._tail.read_latest() or {}
        watch = self._screening.read_watchlist()
        summary = self._screening.summary()
        weekly_review = summary.get("weekly_review") or {}
        perf_ctx = self._read_weekly_performance_context() or weekly_review or {}
        nightly_rows = (nightly.get("screening") or {}).get("data") or []
        tail_rows_raw = tail.get("recommended") or []
        industry_by_symbol: dict[str, str] = {}
        for row in nightly_rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            industry = str(row.get("industry") or "").strip()
            if sym and industry:
                industry_by_symbol[sym] = industry
        tail_rows: list[dict[str, Any]] = []
        for row in tail_rows_raw:
            if not isinstance(row, dict):
                continue
            merged = dict(row)
            sym = str(merged.get("symbol") or "").strip()
            sector_name = str(merged.get("sector_name") or "").strip()
            if (not sector_name) and sym and industry_by_symbol.get(sym):
                merged["sector_name"] = industry_by_symbol[sym]
            tail_rows.append(merged)
        raw_paradigm_pools = tail.get("paradigm_pools") if isinstance(tail.get("paradigm_pools"), dict) else {}
        tail_paradigm_pools: dict[str, list[dict[str, Any]]] = {}
        for pool_id, rows in raw_paradigm_pools.items():
            if not isinstance(rows, list):
                continue
            normalized_rows: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                merged = dict(row)
                sym = str(merged.get("symbol") or "").strip()
                sector_name = str(merged.get("sector_name") or "").strip()
                if (not sector_name) and sym and industry_by_symbol.get(sym):
                    merged["sector_name"] = industry_by_symbol[sym]
                normalized_rows.append(merged)
            tail_paradigm_pools[str(pool_id)] = normalized_rows
        tail_summary = tail.get("summary") if isinstance(tail.get("summary"), dict) else {}
        sector_counter: dict[str, int] = {}
        for row in tail_rows:
            if not isinstance(row, dict):
                continue
            sec = str(row.get("sector_name") or "未标注")
            sector_counter[sec] = sector_counter.get(sec, 0) + 1
        sector_rotation_heatmap = [
            {"sector_name": k, "count": v}
            for k, v in sorted(sector_counter.items(), key=lambda x: (-x[1], x[0]))
        ]
        metrics = perf_ctx.get("metrics") if isinstance(perf_ctx, dict) else {}
        effect_stats = {
            "nightly_candidate_count": len(nightly_rows),
            "tail_recommended_count": len(tail_rows),
            "tail_pools_nonempty_count": tail_summary.get("pools_nonempty_count"),
            "hit_rate_5d_pct": metrics.get("hit_rate_5d_pct") if isinstance(metrics, dict) else None,
            "avg_max_return_5d_pct": metrics.get("avg_max_return_5d_pct") if isinstance(metrics, dict) else None,
            "pause_events_count": metrics.get("pause_events_count") if isinstance(metrics, dict) else None,
        }
        task_execution_monitor = [
            {
                "task_id": "pre-market-sentiment-check",
                "status": "ok" if (summary.get("sentiment_snapshot") or {}).get("precheck_date") == trade_date else "stale",
                "last_run": (summary.get("sentiment_snapshot") or {}).get("precheck_date"),
                "signal": (summary.get("sentiment_snapshot") or {}).get("overall_score"),
            },
            {
                "task_id": "nightly-stock-screening",
                "status": "ok" if nightly.get("run_date") == trade_date else "stale",
                "last_run": nightly.get("run_date"),
                "signal": (nightly.get("screening") or {}).get("quality_score"),
            },
            {
                "task_id": "intraday-tail-screening",
                "status": "ok" if tail.get("run_date") == trade_date else "stale",
                "last_run": tail.get("run_date"),
                "signal": tail_summary.get("recommended_count"),
            },
            {
                "task_id": "weekly-selection-review",
                "status": "ok" if bool(weekly_review) else "missing",
                "last_run": weekly_review.get("as_of") if isinstance(weekly_review, dict) else None,
                "signal": (metrics or {}).get("pause_events_count") if isinstance(metrics, dict) else None,
            },
        ]
        return {
            "watchlist_state": watch,
            "candidates": {
                "nightly": nightly_rows,
                "tail": tail_rows,
            },
            "performance_context": perf_ctx,
            "effect_stats": effect_stats,
            "sector_rotation_heatmap": sector_rotation_heatmap,
            "tail_paradigm_pools": tail_paradigm_pools,
            "task_execution_monitor": task_execution_monitor,
            "alert_thresholds": self._read_alert_thresholds(),
            "_meta": {
                "schema_name": "screening_view_v1",
                "schema_version": "1.0.0",
                "task_id": "intraday-tail-screening",
                "run_id": "",
                "data_layer": "L4",
                "generated_at": "",
                "trade_date": trade_date,
                "quality_status": "degraded" if any(str(x.get("status")) in {"stale", "missing"} for x in task_execution_monitor) else "ok",
                "lineage_refs": [
                    str(self.root / "data" / "screening" / f"{trade_date}.json"),
                    str(self.root / "data" / "tail_screening" / f"{trade_date}.json"),
                ],
            },
        }

    def _ops_jobs_source(self) -> tuple[list[dict[str, Any]], str]:
        jobs_path = Path("/home/xie/.openclaw/cron/jobs.json")
        if not jobs_path.is_file():
            return [], str(jobs_path)
        try:
            root = json.loads(jobs_path.read_text(encoding="utf-8"))
        except Exception:
            return [], str(jobs_path)
        jobs = root.get("jobs") if isinstance(root.get("jobs"), list) else []
        out = [j for j in jobs if isinstance(j, dict)]
        return out, str(jobs_path)

    def _read_ops_snapshot(self, trade_date: str) -> dict[str, Any] | None:
        path = self.root / "data" / "semantic" / "ops_events" / f"{trade_date}.json"
        obj = _read_json(path)
        if not isinstance(obj, dict):
            return None
        data = obj.get("data") if isinstance(obj.get("data"), dict) else None
        meta = obj.get("_meta") if isinstance(obj.get("_meta"), dict) else None
        if not isinstance(data, dict):
            return None
        if isinstance(meta, dict):
            merged = dict(data)
            merged["_meta"] = meta
            return merged
        return data

    def _ops_runs_dir(self) -> Path:
        return Path("/home/xie/.openclaw/cron/runs")

    def _schedule_label(self, schedule: dict[str, Any]) -> str:
        if not isinstance(schedule, dict):
            return ""
        kind = str(schedule.get("kind") or "")
        if kind == "cron":
            expr = str(schedule.get("expr") or "")
            tz = str(schedule.get("tz") or "")
            return f"{expr} ({tz})".strip()
        if kind == "every":
            try:
                ms = int(schedule.get("everyMs") or 0)
            except Exception:
                ms = 0
            if ms > 0:
                minutes = max(1, ms // 60000)
                return f"every {minutes}m"
        return kind

    def _last_finished_run(self, job_id: str) -> dict[str, Any]:
        p = self._ops_runs_dir() / f"{job_id}.jsonl"
        rows = _read_jsonl(p)
        for row in reversed(rows):
            if str(row.get("action") or "") == "finished":
                return row
        return {}

    def _repair_hint(self, error: str) -> str:
        e = (error or "").strip()
        if not e:
            return "无"
        hint_map: list[tuple[str, str]] = [
            (r"Channel is required when multiple channels are configured", "补充 delivery.channel 或改为 delivery.mode=none"),
            (r"requires target <chatId\|user:openId\|chat:chatId>", "为 Feishu 发送配置 chatId/openId；或移除 announce 投递"),
            (r"ERROR_NO_DELIVERY_TOOL_CALL", "调整任务提示词，避免将通知失败设为硬失败"),
            (r"No such file or directory", "修正脚本绝对路径，先在目标目录确认文件存在"),
            (r"can't open file", "修正 Python 脚本路径，并使用绝对解释器路径"),
            (r"Request failed with status code 400", "检查消息长度/格式与目标参数，缩短摘要并重试"),
            (r"401|unauthorized|鉴权", "检查 .env 中密钥是否生效并确认 provider 权限"),
        ]
        lower = e.lower()
        for pat, hint in hint_map:
            if re.search(pat, e, flags=re.I):
                return hint
        if "timeout" in lower:
            return "提升 timeoutSeconds 或拆分任务步骤，先确认最慢环节"
        return "查看 runs/*.jsonl 的 lastError 与 summary，按错误关键词修复"

    def ops_events(self, trade_date: str = "") -> dict[str, Any]:
        """Batch2 扩展：统一数据层 L4 的执行审计/采集质量事件视图。"""
        td = trade_date.strip() if isinstance(trade_date, str) else ""
        if td and validate_screening_date_key(td):
            snap = self._read_ops_snapshot(td)
            if isinstance(snap, dict):
                return snap
        jobs, lineage = self._ops_jobs_source()
        execution: list[dict[str, Any]] = []
        collection: list[dict[str, Any]] = []
        task_health: list[dict[str, Any]] = []
        for job in jobs:
            payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
            tools = payload.get("toolsAllow") if isinstance(payload.get("toolsAllow"), list) else []
            state = job.get("state") if isinstance(job.get("state"), dict) else {}
            consecutive = state.get("consecutiveErrors")
            status = state.get("lastRunStatus") or state.get("lastStatus")
            quality_status = "degraded" if (isinstance(consecutive, int) and consecutive > 0) else "ok"
            row = {
                "task_id": str(job.get("id") or ""),
                "name": str(job.get("name") or ""),
                "enabled": bool(job.get("enabled")),
                "schedule": self._schedule_label(job.get("schedule") if isinstance(job.get("schedule"), dict) else {}),
                "last_run_status": status,
                "last_run_at_ms": state.get("lastRunAtMs"),
                "next_run_at_ms": state.get("nextRunAtMs"),
                "consecutive_errors": consecutive,
                "tools_allow": tools,
                "quality_status": quality_status,
                "lineage_refs": [lineage],
            }
            last_finished = self._last_finished_run(str(job.get("id") or ""))
            run_status = str(last_finished.get("status") or status or "")
            run_error = str(last_finished.get("error") or state.get("lastError") or "")
            health_quality = "degraded" if run_status == "error" or (isinstance(consecutive, int) and consecutive > 0) else "ok"
            task_health.append(
                {
                    "task_id": str(job.get("id") or ""),
                    "name": str(job.get("name") or ""),
                    "enabled": bool(job.get("enabled")),
                    "schedule": self._schedule_label(job.get("schedule") if isinstance(job.get("schedule"), dict) else {}),
                    "last_run_status": run_status,
                    "quality_status": health_quality,
                    "consecutive_errors": consecutive,
                    "last_run_at_ms": last_finished.get("ts") or state.get("lastRunAtMs"),
                    "next_run_at_ms": state.get("nextRunAtMs"),
                    "duration_ms": last_finished.get("durationMs") or state.get("lastDurationMs"),
                    "error": run_error,
                    "repair_hint": self._repair_hint(run_error),
                    "run_log_path": str(self._ops_runs_dir() / f"{str(job.get('id') or '')}.jsonl"),
                    "last_error_at_ms": (last_finished.get("ts") if run_status == "error" else None),
                    "tools_allow": tools,
                    "lineage_refs": [lineage, str(self._ops_runs_dir() / f"{str(job.get('id') or '')}.jsonl")],
                }
            )
            if any(t == "tool_run_data_cache_job" for t in tools):
                collection.append(row)
            else:
                execution.append(row)
        task_health.sort(key=lambda x: str(x.get("task_id") or ""))
        return {
            "execution_audit_events": execution,
            "collection_quality_events": collection,
            "task_health_events": task_health,
            "_meta": {
                "schema_name": "ops_events_view_v1",
                "schema_version": "1.0.0",
                "task_id": "openclaw-jobs-inventory",
                "run_id": "",
                "data_layer": "L4",
                "generated_at": "",
                "trade_date": td or _today_utc(),
                "quality_status": "ok",
                "lineage_refs": [lineage],
            },
        }

    def research_metrics(self, trade_date: str = "", window: int = 5) -> dict[str, Any]:
        td = self._resolve_trade_date(trade_date)
        w = max(1, min(int(window or 5), 20))
        dashboard = self.dashboard()
        view = self.screening_view(td)
        sentiment = dashboard.get("sentiment_temperature") if isinstance(dashboard.get("sentiment_temperature"), dict) else {}
        risk = dashboard.get("risk_snapshot") if isinstance(dashboard.get("risk_snapshot"), dict) else {}

        dates = self.semantic_trade_dates()
        selected_dates = [d for d in dates if d <= td][-w:]
        score_series: list[float | None] = []
        for d in selected_dates:
            snap = self._read_sentiment_snapshot(d) or {}
            sc = snap.get("overall_score")
            if not isinstance(sc, (int, float)):
                score_series.append(None)
            else:
                score_series.append(float(sc))
        trend_deltas: list[float] = []
        for i in range(1, len(score_series)):
            a, b = score_series[i - 1], score_series[i]
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                trend_deltas.append(round(float(b) - float(a), 4))

        candidates = (view.get("candidates") if isinstance(view.get("candidates"), dict) else {})
        nightly = candidates.get("nightly") if isinstance(candidates.get("nightly"), list) else []
        tail = candidates.get("tail") if isinstance(candidates.get("tail"), list) else []
        effect_stats = view.get("effect_stats") if isinstance(view.get("effect_stats"), dict) else {}
        hit_rate_5d = effect_stats.get("hit_rate_5d_pct")
        if not isinstance(hit_rate_5d, (int, float)):
            hit_rate_5d = None

        task_monitor = view.get("task_execution_monitor") if isinstance(view.get("task_execution_monitor"), list) else []
        stale_or_missing = [
            row for row in task_monitor
            if isinstance(row, dict) and str(row.get("status")) in {"stale", "missing"}
        ]
        quality_status = "degraded" if stale_or_missing else "ok"
        if (sentiment.get("quality_status") or {}).get("degraded"):
            quality_status = "degraded"

        return {
            "sentiment_trend": {
                "current_score": sentiment.get("score"),
                "current_stage": sentiment.get("stage"),
                "dispersion": sentiment.get("dispersion"),
                "score_series": score_series,
                "trend_5d": trend_deltas,
            },
            "screening_effectiveness": {
                "nightly_candidates": len(nightly),
                "tail_recommendations": len(tail),
                "hit_rate_5d": hit_rate_5d,
                "pause_events": effect_stats.get("pause_events_count"),
                "extreme_alert_count": risk.get("extreme_alert_count"),
            },
            "task_health": {
                "stale_or_missing_count": len(stale_or_missing),
                "stale_or_missing_tasks": [str(x.get("task_id") or "") for x in stale_or_missing],
            },
            "_meta": {
                "schema_name": "research_metrics_v1",
                "schema_version": "1.0.0",
                "task_id": "research-metrics-aggregation",
                "run_id": "",
                "data_layer": "L4",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "trade_date": td,
                "quality_status": quality_status,
                "lineage_refs": [
                    f"data/semantic/screening_view/{td}.json",
                    f"data/semantic/sentiment_snapshot/{td}.json",
                ],
            },
        }

    def research_diagnostics(self, trade_date: str = "", window: int = 5) -> dict[str, Any]:
        td = self._resolve_trade_date(trade_date)
        metrics = self.research_metrics(td, window=window)
        timeline = self.timeline(td)
        events = timeline.get("events") if isinstance(timeline.get("events"), list) else []
        degraded_events = [
            {
                "task_id": str(e.get("task_id") or ""),
                "event_time": str(e.get("event_time") or ""),
                "summary": str(e.get("summary") or ""),
            }
            for e in events
            if isinstance(e, dict) and str(e.get("quality_status") or "") == "degraded"
        ]
        return {
            "metrics": metrics,
            "diagnostics": {
                "degraded_event_count": len(degraded_events),
                "degraded_events": degraded_events[:20],
            },
            "_meta": {
                "schema_name": "research_diagnostics_v1",
                "schema_version": "1.0.0",
                "task_id": "research-diagnostics-aggregation",
                "run_id": "",
                "data_layer": "L4",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "trade_date": td,
                "quality_status": "degraded" if degraded_events else "ok",
                "lineage_refs": [
                    f"data/semantic/timeline_feed/{td}.jsonl",
                    f"data/semantic/screening_view/{td}.json",
                ],
            },
        }

    def factor_diagnostics(self, trade_date: str = "", period: str = "week") -> dict[str, Any]:
        td = self._resolve_trade_date(trade_date)
        view = self.screening_view(td)
        candidates = (view.get("candidates") if isinstance(view.get("candidates"), dict) else {})
        nightly = candidates.get("nightly") if isinstance(candidates.get("nightly"), list) else []
        scored = [r for r in nightly if isinstance(r, dict) and isinstance(r.get("score"), (int, float))]
        sorted_rows = sorted(scored, key=lambda x: float(x.get("score") or 0.0), reverse=True)
        bucket = max(1, len(sorted_rows) // 3)
        top = sorted_rows[:bucket]
        bottom = sorted_rows[-bucket:] if sorted_rows else []

        def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
            vals = [float(r.get(key)) for r in rows if isinstance(r.get(key), (int, float))]
            if not vals:
                return None
            return float(sum(vals) / len(vals))

        spread = None
        top_ret = _avg(top, "pct_change")
        bot_ret = _avg(bottom, "pct_change")
        if isinstance(top_ret, (int, float)) and isinstance(bot_ret, (int, float)):
            spread = round(float(top_ret) - float(bot_ret), 4)

        hit_top = None
        if top:
            c = 0
            t = 0
            for r in top:
                pc = r.get("pct_change")
                if isinstance(pc, (int, float)):
                    t += 1
                    if float(pc) > 0:
                        c += 1
            if t > 0:
                hit_top = round(c / t, 4)

        factors = [
            {
                "name": "composite_score",
                "ic_proxy": spread,
                "hit_rate_top_bucket": hit_top,
                "sample_size": len(sorted_rows),
                "stability": 1.0 if len(sorted_rows) >= 3 else None,
            }
        ]
        return {
            "period": period,
            "factors": factors,
            "_meta": {
                "schema_name": "factor_diagnostics_v1",
                "schema_version": "1.0.0",
                "task_id": "factor-diagnostics",
                "run_id": "",
                "data_layer": "L4",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "trade_date": td,
                "quality_status": "ok" if scored else "degraded",
                "lineage_refs": [f"data/semantic/screening_view/{td}.json"],
            },
        }

    def strategy_attribution(self, trade_date: str = "") -> dict[str, Any]:
        td = self._resolve_trade_date(trade_date)
        view = self.screening_view(td)
        tail = ((view.get("candidates") or {}).get("tail") if isinstance(view.get("candidates"), dict) else [])
        by_paradigm: dict[str, dict[str, Any]] = {}
        for row in tail if isinstance(tail, list) else []:
            if not isinstance(row, dict):
                continue
            tags = row.get("source_tags") if isinstance(row.get("source_tags"), list) else []
            for tag in tags:
                k = str(tag or "").strip() or "unknown"
                if k not in by_paradigm:
                    by_paradigm[k] = {"recommendations": 0, "avg_score": 0.0}
                by_paradigm[k]["recommendations"] += 1
                sc = row.get("score")
                if isinstance(sc, (int, float)):
                    by_paradigm[k]["avg_score"] += float(sc)
        for v in by_paradigm.values():
            n = max(1, int(v["recommendations"]))
            v["avg_score"] = round(float(v["avg_score"]) / n, 4)

        nightly = ((view.get("candidates") or {}).get("nightly") if isinstance(view.get("candidates"), dict) else [])
        gate = view.get("task_execution_monitor") if isinstance(view.get("task_execution_monitor"), list) else []
        stale = sum(1 for r in gate if isinstance(r, dict) and str(r.get("status")) in {"stale", "missing"})
        return {
            "attribution": {
                "by_paradigm": by_paradigm,
                "by_task_stage": {
                    "nightly": {"recommendations": len(nightly) if isinstance(nightly, list) else 0},
                    "tail": {"recommendations": len(tail) if isinstance(tail, list) else 0},
                },
                "gate_impact": {
                    "stale_or_missing_tasks": stale,
                },
            },
            "_meta": {
                "schema_name": "strategy_attribution_v1",
                "schema_version": "1.0.0",
                "task_id": "strategy-attribution",
                "run_id": "",
                "data_layer": "L4",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "trade_date": td,
                "quality_status": "ok",
                "lineage_refs": [f"data/semantic/screening_view/{td}.json"],
            },
        }

    def orchestration_timeline(self, trade_date: str = "") -> dict[str, Any]:
        td = self._resolve_trade_date(trade_date)
        rows = _read_jsonl(self.root / "data" / "decisions" / "orchestration" / "events" / f"{td}.jsonl")
        events: list[dict[str, Any]] = []
        for row in rows:
            meta = row.get("_meta") if isinstance(row.get("_meta"), dict) else {}
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            if not data:
                continue
            events.append(
                {
                    "event_id": data.get("event_id"),
                    "event_time": data.get("event_time"),
                    "task_id": data.get("task_id") or meta.get("task_id"),
                    "run_id": data.get("run_id") or meta.get("run_id"),
                    "from_state": data.get("from_state"),
                    "to_state": data.get("to_state"),
                    "reason": data.get("reason"),
                    "trigger_source": data.get("trigger_source"),
                    "idempotency_key": data.get("idempotency_key"),
                    "quality_status": meta.get("quality_status"),
                }
            )
        stats = {
            "total_events": len(events),
            "succeeded_count": sum(1 for e in events if e.get("to_state") == "succeeded"),
            "failed_count": sum(1 for e in events if e.get("to_state") == "failed"),
            "skipped_count": sum(1 for e in events if e.get("to_state") == "skipped"),
            "dependency_trigger_count": sum(1 for e in events if e.get("trigger_source") == "dependency"),
            "cron_trigger_count": sum(1 for e in events if e.get("trigger_source") == "cron"),
        }
        return {
            "trade_date": td,
            "events": events,
            "stats": stats,
            "_meta": {
                "schema_name": "orchestration_timeline_v1",
                "schema_version": "1.0.0",
                "task_id": "orchestration-timeline-aggregation",
                "run_id": "",
                "data_layer": "L4",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "trade_date": td,
                "quality_status": "ok",
                "lineage_refs": [f"data/decisions/orchestration/events/{td}.jsonl"],
            },
        }

    def task_dependency_health(self, trade_date: str = "") -> dict[str, Any]:
        td = self._resolve_trade_date(trade_date)
        timeline = self.orchestration_timeline(td)
        events = timeline.get("events") if isinstance(timeline.get("events"), list) else []
        latest_by_task: dict[str, dict[str, Any]] = {}
        for event in events:
            if not isinstance(event, dict):
                continue
            task_id = str(event.get("task_id") or "")
            if not task_id:
                continue
            latest_by_task[task_id] = event
        unhealthy_tasks: list[dict[str, Any]] = []
        timeout_count = 0
        skip_count = 0
        for task_id, event in latest_by_task.items():
            reason = str(event.get("reason") or "")
            to_state = str(event.get("to_state") or "")
            if to_state == "skipped":
                skip_count += 1
            if "dependency_timeout" in reason:
                timeout_count += 1
            if to_state in {"failed", "skipped"}:
                unhealthy_tasks.append(
                    {
                        "task_id": task_id,
                        "state": to_state,
                        "reason": reason,
                        "trigger_source": event.get("trigger_source"),
                    }
                )
        total_tasks = max(1, len(latest_by_task))
        satisfied_count = total_tasks - len(unhealthy_tasks)
        return {
            "trade_date": td,
            "dependency_graph": {
                "pre-market-sentiment-check": [],
                "strategy-calibration": ["pre-market-sentiment-check"],
                "extreme-sentiment-monitor": ["pre-market-sentiment-check"],
                "nightly-stock-screening": [
                    "pre-market-sentiment-check",
                    "strategy-calibration",
                    "extreme-sentiment-monitor",
                ],
                "intraday-tail-screening": [
                    "pre-market-sentiment-check",
                    "extreme-sentiment-monitor",
                    "nightly-stock-screening",
                ],
                "position-tracking": ["nightly-stock-screening"],
                "weekly-selection-review": ["nightly-stock-screening", "intraday-tail-screening", "position-tracking"],
            },
            "health_metrics": {
                "satisfaction_rate": round(float(satisfied_count) / float(total_tasks), 4),
                "timeout_count": timeout_count,
                "skip_count": skip_count,
                "avg_wait_seconds": None,
            },
            "unhealthy_tasks": unhealthy_tasks,
            "_meta": {
                "schema_name": "task_dependency_health_v1",
                "schema_version": "1.0.0",
                "task_id": "task-dependency-health-aggregation",
                "run_id": "",
                "data_layer": "L4",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "trade_date": td,
                "quality_status": "ok" if not unhealthy_tasks else "degraded",
                "lineage_refs": [f"data/decisions/orchestration/events/{td}.jsonl"],
            },
        }
