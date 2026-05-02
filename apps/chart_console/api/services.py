from __future__ import annotations

import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from src.services.backtest_service import BacktestConfig, BacktestService
from src.services.indicator_service import IndicatorService
from src.services.market_data_service import MarketDataService
from src.services.workspace_service import WorkspaceService

from apps.chart_console.api.screening_reader import ScreeningReader, validate_screening_date_key
from apps.chart_console.api.semantic_reader import SemanticReader
from apps.chart_console.api.tail_screening_reader import TailScreeningReader


def _repo_root_for_data() -> Path:
    """数据目录（含 `data/sentiment_check/`）所在仓库根。默认为本文件上溯三级的 `etf-options-ai-assistant`。

    若进程工作目录或安装路径与落盘数据不一致，可设置环境变量指向实际仓库：
    `ETF_OPTIONS_ASSISTANT_ROOT` 或 `CHART_CONSOLE_REPO_ROOT`。
    """
    for key in ("ETF_OPTIONS_ASSISTANT_ROOT", "CHART_CONSOLE_REPO_ROOT"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        p = Path(raw).expanduser().resolve()
        if p.is_dir():
            return p
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root_for_data()
ALERTS_PATH = ROOT / "config" / "alerts.yaml"


def _openclaw_data_china_stock_root() -> Path:
    """Resolve plugin dev directory for health snapshot JSON (symlink or env)."""
    for key in ("OPENCLAW_DATA_CHINA_STOCK_REPO", "OPENCLAW_CHINA_STOCK_PLUGIN_ROOT"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            p = Path(raw).expanduser().resolve()
            if p.is_dir():
                return p
    link = ROOT / "plugins" / "data_collection"
    if link.is_symlink():
        try:
            target = Path(os.readlink(link)).resolve()
            # .../openclaw-data-china-stock/plugins/data_collection -> repo root
            return target.parent.parent
        except Exception:
            pass
    return Path("/home/xie/openclaw-data-china-stock")
MARKET_DATA_PATH = ROOT / "config" / "domains" / "market_data.yaml"
ANALYTICS_PATH = ROOT / "config" / "domains" / "analytics.yaml"
ROTATION_CONFIG_PATH = ROOT / "config" / "rotation_config.yaml"
FEATURE_FLAGS_PATH = ROOT / "config" / "feature_flags.json"


class ApiServices:
    def __init__(self) -> None:
        self.market = MarketDataService()
        self.indicator = IndicatorService()
        self.backtest = BacktestService()
        self.workspace = WorkspaceService()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._screening = ScreeningReader(ROOT)
        self._tail_screening = TailScreeningReader(ROOT)
        self._semantic = SemanticReader(ROOT)

    def _feature_flag(self, key: str, default: bool = False) -> bool:
        try:
            obj = json.loads(FEATURE_FLAGS_PATH.read_text(encoding="utf-8")) if FEATURE_FLAGS_PATH.is_file() else {}
        except Exception:
            obj = {}
        val = obj.get(key, default)
        return bool(val)

    def _prefer_new(self) -> bool:
        return self._feature_flag("prefer_new", self._feature_flag("semantic_read_enabled", False))

    def cache_get(self, key: str, ttl_sec: int) -> Any | None:
        hit = self._cache.get(key)
        if not hit:
            return None
        ts, value = hit
        if time.time() - ts > ttl_sec:
            return None
        return value

    def cache_set(self, key: str, value: Any) -> Any:
        self._cache[key] = (time.time(), value)
        return value

    def get_ohlcv(self, symbol: str, lookback_days: int) -> dict[str, Any]:
        key = f"ohlcv:{symbol}:{lookback_days}"
        cached = self.cache_get(key, 15)
        if cached is not None:
            return cached
        out = self.market.get_ohlcv(symbol=symbol, lookback_days=lookback_days)
        return self.cache_set(key, out)

    def get_indicators(self, symbol: str, lookback_days: int, timeframe_minutes: int | None, ma_periods: list[int]) -> dict[str, Any]:
        key = f"ind:{symbol}:{lookback_days}:{timeframe_minutes}:{','.join(str(x) for x in ma_periods)}"
        cached = self.cache_get(key, 10)
        if cached is not None:
            return cached
        out = self.indicator.calculate(
            symbol=symbol,
            lookback_days=lookback_days,
            timeframe_minutes=timeframe_minutes,
            ma_periods=ma_periods,
        )
        return self.cache_set(key, out)

    def get_backtest(self, symbol: str, lookback_days: int, fast_ma: int, slow_ma: int, fee_bps: float, slippage_bps: float) -> dict[str, Any]:
        cfg = BacktestConfig(
            symbol=symbol,
            lookback_days=lookback_days,
            fast_ma=fast_ma,
            slow_ma=slow_ma,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        return self.backtest.run_ma_crossover(cfg)

    def get_alert_replay(self) -> dict[str, Any]:
        events_path = ROOT / "data" / "alerts" / "internal_alert_events.jsonl"
        rows: list[dict[str, Any]] = []
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        obj.setdefault("diagnostics", {})
                        obj["diagnostics"]["is_dedup"] = obj.get("status") == "dedup_skipped"
                        obj["diagnostics"]["is_cooldown"] = obj.get("status") == "cooldown_skipped"
                        rows.append(obj)
                except Exception:
                    continue
        return {"success": True, "message": "ok", "data": rows[-1000:]}

    def get_alerts_config_text(self) -> dict[str, Any]:
        """Return raw alerts.yaml content for the config center editor."""
        if not ALERTS_PATH.exists():
            return {"success": True, "message": "ok", "data": {"path": str(ALERTS_PATH), "text": ""}}
        try:
            return {
                "success": True,
                "message": "ok",
                "data": {"path": str(ALERTS_PATH), "text": ALERTS_PATH.read_text(encoding="utf-8")},
            }
        except Exception as e:
            return {"success": False, "message": f"read alerts.yaml failed: {e}"}

    def save_alerts_config_text(self, text: str) -> dict[str, Any]:
        """Save alerts.yaml with timestamped backup for quick rollback."""
        try:
            ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            if ALERTS_PATH.exists():
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = ALERTS_PATH.with_name(f"alerts.yaml.bak.{ts}")
                try:
                    backup.write_text(ALERTS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    # Backup failure should not block saving; still try to write the new file.
                    pass
            ALERTS_PATH.write_text(text, encoding="utf-8")
            return {"success": True, "message": "ok", "data": {"path": str(ALERTS_PATH)}}
        except Exception as e:
            return {"success": False, "message": f"save alerts.yaml failed: {e}"}

    def get_market_data_config_text(self) -> dict[str, Any]:
        if not MARKET_DATA_PATH.exists():
            return {"success": True, "message": "ok", "data": {"path": str(MARKET_DATA_PATH), "text": ""}}
        try:
            return {
                "success": True,
                "message": "ok",
                "data": {"path": str(MARKET_DATA_PATH), "text": MARKET_DATA_PATH.read_text(encoding="utf-8")},
            }
        except Exception as e:
            return {"success": False, "message": f"read market_data.yaml failed: {e}"}

    def save_market_data_config_text(self, text: str) -> dict[str, Any]:
        try:
            MARKET_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
            if MARKET_DATA_PATH.exists():
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = MARKET_DATA_PATH.with_name(f"{MARKET_DATA_PATH.name}.bak.{ts}")
                try:
                    backup.write_text(MARKET_DATA_PATH.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass
            MARKET_DATA_PATH.write_text(text, encoding="utf-8")
            return {"success": True, "message": "ok", "data": {"path": str(MARKET_DATA_PATH)}}
        except Exception as e:
            return {"success": False, "message": f"save market_data.yaml failed: {e}"}

    def get_analytics_config_text(self) -> dict[str, Any]:
        if not ANALYTICS_PATH.exists():
            return {"success": True, "message": "ok", "data": {"path": str(ANALYTICS_PATH), "text": ""}}
        try:
            return {
                "success": True,
                "message": "ok",
                "data": {"path": str(ANALYTICS_PATH), "text": ANALYTICS_PATH.read_text(encoding="utf-8")},
            }
        except Exception as e:
            return {"success": False, "message": f"read analytics.yaml failed: {e}"}

    def save_analytics_config_text(self, text: str) -> dict[str, Any]:
        try:
            ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
            if ANALYTICS_PATH.exists():
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = ANALYTICS_PATH.with_name(f"{ANALYTICS_PATH.name}.bak.{ts}")
                try:
                    backup.write_text(ANALYTICS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass
            ANALYTICS_PATH.write_text(text, encoding="utf-8")
            return {"success": True, "message": "ok", "data": {"path": str(ANALYTICS_PATH)}}
        except Exception as e:
            return {"success": False, "message": f"save analytics.yaml failed: {e}"}

    def get_rotation_config_text(self) -> dict[str, Any]:
        if not ROTATION_CONFIG_PATH.exists():
            return {"success": True, "message": "ok", "data": {"path": str(ROTATION_CONFIG_PATH), "text": ""}}
        try:
            return {
                "success": True,
                "message": "ok",
                "data": {"path": str(ROTATION_CONFIG_PATH), "text": ROTATION_CONFIG_PATH.read_text(encoding="utf-8")},
            }
        except Exception as e:
            return {"success": False, "message": f"read rotation_config.yaml failed: {e}"}

    def save_rotation_config_text(self, text: str) -> dict[str, Any]:
        try:
            ROTATION_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            if ROTATION_CONFIG_PATH.exists():
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = ROTATION_CONFIG_PATH.with_name(f"{ROTATION_CONFIG_PATH.name}.bak.{ts}")
                try:
                    backup.write_text(ROTATION_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass
            ROTATION_CONFIG_PATH.write_text(text, encoding="utf-8")
            return {"success": True, "message": "ok", "data": {"path": str(ROTATION_CONFIG_PATH)}}
        except Exception as e:
            return {"success": False, "message": f"save rotation_config.yaml failed: {e}"}

    def get_screening_summary(self) -> dict[str, Any]:
        if self._prefer_new():
            return {"success": True, "message": "ok", "data": self._semantic.dashboard()}
        return {"success": True, "message": "ok", "data": self._screening.summary()}

    def get_screening_history(self) -> dict[str, Any]:
        return {"success": True, "message": "ok", "data": self._screening.history()}

    def get_screening_by_date(self, date_key: str) -> tuple[dict[str, Any], int]:
        if not validate_screening_date_key((date_key or "").strip()):
            return {"success": False, "message": "invalid date (use YYYY-MM-DD)", "data": None}, 400
        if self._prefer_new():
            return self.get_semantic_screening_view(date_key)
        art = self._screening.read_artifact_by_date(date_key.strip())
        if art is None:
            return {"success": False, "message": "not found", "data": None}, 404
        return {"success": True, "message": "ok", "data": art}, 200

    def get_tail_screening_summary(self) -> dict[str, Any]:
        if self._prefer_new():
            return {"success": True, "message": "ok", "data": {"latest": {"recommended": self._semantic.dashboard().get("top_recommendations") or []}}}
        return {"success": True, "message": "ok", "data": self._tail_screening.summary()}

    def get_tail_screening_history(self) -> dict[str, Any]:
        return {"success": True, "message": "ok", "data": self._tail_screening.history()}

    def get_tail_screening_by_date(self, date_key: str) -> tuple[dict[str, Any], int]:
        date_key = (date_key or "").strip()
        if not validate_screening_date_key(date_key):
            return {"success": False, "message": "invalid date (use YYYY-MM-DD)", "data": None}, 400
        if self._prefer_new():
            return self.get_semantic_screening_view(date_key)
        art = self._tail_screening.read_by_date(date_key)
        if art is None:
            return {"success": False, "message": "not found", "data": None}, 404
        return {"success": True, "message": "ok", "data": art}, 200

    def get_semantic_dashboard(self) -> dict[str, Any]:
        return {"success": True, "message": "ok", "data": self._semantic.dashboard()}

    def get_semantic_timeline(self, trade_date: str) -> tuple[dict[str, Any], int]:
        try:
            data = self._semantic.timeline(trade_date)
        except ValueError:
            return {"success": False, "message": "invalid trade_date (use YYYY-MM-DD)", "data": None}, 400
        return {"success": True, "message": "ok", "data": data}, 200

    def get_semantic_screening_view(self, trade_date: str) -> tuple[dict[str, Any], int]:
        try:
            data = self._semantic.screening_view(trade_date)
        except ValueError:
            return {"success": False, "message": "invalid trade_date (use YYYY-MM-DD)", "data": None}, 400
        return {"success": True, "message": "ok", "data": data}, 200

    def get_semantic_screening_candidates(self, trade_date: str) -> tuple[dict[str, Any], int]:
        try:
            data = self._semantic.screening_candidates(trade_date)
        except ValueError:
            return {"success": False, "message": "invalid trade_date (use YYYY-MM-DD)", "data": None}, 400
        return {"success": True, "message": "ok", "data": data}, 200

    def get_ops_events(self, trade_date: str = "") -> dict[str, Any]:
        # 兼容旧接口：内部已切到统一语义层
        return {"success": True, "message": "ok", "data": self._semantic.ops_events(trade_date)}

    def get_semantic_ops_events(self, trade_date: str = "") -> dict[str, Any]:
        return {"success": True, "message": "ok", "data": self._semantic.ops_events(trade_date)}

    def get_semantic_ops_run_detail(self, task_id: str = "", limit: int = 80) -> dict[str, Any]:
        data = self._semantic.ops_run_detail(task_id=str(task_id or ""), limit=int(limit or 80))
        return {"success": True, "message": "ok", "data": data}

    def get_semantic_data_source_health(self) -> dict[str, Any]:
        """Read-only: `source_health_snapshot.json` from plugin repo (P2-data-health)."""
        p = _openclaw_data_china_stock_root() / "data" / "meta" / "source_health_snapshot.json"
        if not p.is_file():
            return {
                "success": True,
                "message": "no_snapshot",
                "data": {
                    "sources": [],
                    "snapshot_path": str(p),
                    "hint": "Run plugin tool_probe_source_health with write_snapshot=true",
                },
            }
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return {"success": False, "message": f"invalid_json: {e}", "data": None}
        return {"success": True, "message": "ok", "data": doc}

    def get_semantic_trade_dates(self) -> dict[str, Any]:
        dates = self._semantic.semantic_trade_dates()
        return {"success": True, "message": "ok", "data": dates}

    def get_semantic_rotation_trade_dates(self) -> dict[str, Any]:
        dates = self._semantic.rotation_trade_dates()
        return {"success": True, "message": "ok", "data": dates}

    def get_semantic_rotation_latest(self, trade_date: str = "") -> dict[str, Any]:
        data = self._semantic.rotation_latest(trade_date)
        return {"success": True, "message": "ok", "data": data}

    def get_semantic_rotation_heatmap(self, trade_date: str = "") -> dict[str, Any]:
        data = self._semantic.rotation_heatmap(trade_date)
        return {"success": True, "message": "ok", "data": data}

    def get_semantic_etf_share_dashboard(self, trade_date: str = "") -> dict[str, Any]:
        data = self._semantic.etf_share_dashboard(trade_date)
        return {"success": True, "message": "ok", "data": data}

    def get_semantic_six_index_next_day(self, trade_date: str = "") -> dict[str, Any]:
        data = self._semantic.six_index_next_day(trade_date)
        return {"success": True, "message": "ok", "data": data}

    def get_semantic_six_index_next_day_trade_dates(self) -> dict[str, Any]:
        dates = self._semantic.six_index_next_day_trade_dates()
        return {"success": True, "message": "ok", "data": dates}

    def get_semantic_research_metrics(self, trade_date: str = "", window: int = 5) -> dict[str, Any]:
        data = self._semantic.research_metrics(trade_date, window=window)
        return {"success": True, "message": "ok", "data": data}

    def get_semantic_research_diagnostics(self, trade_date: str = "", window: int = 5) -> dict[str, Any]:
        data = self._semantic.research_diagnostics(trade_date, window=window)
        return {"success": True, "message": "ok", "data": data}

    def get_semantic_factor_diagnostics(self, trade_date: str = "", period: str = "week") -> dict[str, Any]:
        data = self._semantic.factor_diagnostics(trade_date, period=period)
        return {"success": True, "message": "ok", "data": data}

    def get_semantic_strategy_attribution(self, trade_date: str = "") -> dict[str, Any]:
        data = self._semantic.strategy_attribution(trade_date)
        return {"success": True, "message": "ok", "data": data}

    def get_semantic_orchestration_timeline(self, trade_date: str = "") -> dict[str, Any]:
        data = self._semantic.orchestration_timeline(trade_date)
        return {"success": True, "message": "ok", "data": data}

    def get_semantic_task_dependency_health(self, trade_date: str = "") -> dict[str, Any]:
        data = self._semantic.task_dependency_health(trade_date)
        return {"success": True, "message": "ok", "data": data}

    def get_semantic_global_market_snapshot(self, trade_date: str = "", refresh: bool = False) -> tuple[dict[str, Any], int]:
        from apps.chart_console.api.market_snapshot_build import build_global_market_snapshot, persist_snapshot

        td = str(trade_date or "").strip() or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        path = ROOT / "data" / "semantic" / "global_market_snapshot" / f"{td}.json"
        try:
            if refresh or not path.is_file():
                doc = build_global_market_snapshot(td)
                persist_snapshot(ROOT, "global_market_snapshot", td, doc)
        except Exception as e:
            return {"success": False, "message": f"build_failed:{e}", "data": self._semantic.global_market_snapshot(td)}, 500
        data = self._semantic.global_market_snapshot(td)
        return {"success": True, "message": "ok", "data": data}, 200

    def get_semantic_qdii_futures_snapshot(self, trade_date: str = "", refresh: bool = False) -> tuple[dict[str, Any], int]:
        from apps.chart_console.api.market_snapshot_build import (
            build_qdii_futures_snapshot,
            persist_qdii_futures_l3_events,
            persist_snapshot,
        )

        td = str(trade_date or "").strip() or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        path = ROOT / "data" / "semantic" / "qdii_futures_snapshot" / f"{td}.json"
        try:
            if refresh or not path.is_file():
                doc = build_qdii_futures_snapshot(td)
                persist_snapshot(ROOT, "qdii_futures_snapshot", td, doc)
                persist_qdii_futures_l3_events(ROOT, td, doc)
        except Exception as e:
            return {"success": False, "message": f"build_failed:{e}", "data": self._semantic.qdii_futures_snapshot(td)}, 500
        data = self._semantic.qdii_futures_snapshot(td)
        return {"success": True, "message": "ok", "data": data}, 200

    def record_fallback_event(self, primary_url: str, fallback_url: str, reason: str = "") -> dict[str, Any]:
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        out_path = ROOT / "data" / "meta" / "evidence" / "fallback_events.jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "event_time": now,
            "primary_url": str(primary_url or ""),
            "fallback_url": str(fallback_url or ""),
            "reason": str(reason or ""),
        }
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return {"success": True, "message": "ok", "data": payload}
