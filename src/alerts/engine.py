from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz
import yaml

from plugins.notification.send_signal_alert import tool_send_signal_alert
from src.alerts.rules import AlertRule, parse_rule, validate_rule_obj
from src.services.indicator_service import IndicatorService


def _now_shanghai() -> datetime:
    return datetime.now(pytz.timezone("Asia/Shanghai"))


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _compare(operator: str, actual: float, target: float) -> bool:
    if operator == ">":
        return actual > target
    if operator == ">=":
        return actual >= target
    if operator == "<":
        return actual < target
    if operator == "<=":
        return actual <= target
    if operator == "==":
        return actual == target
    if operator == "!=":
        return actual != target
    return False


def _extract_metric(snapshot: Dict[str, Any], metric: str) -> float | None:
    m = metric.lower()
    indicators = snapshot.get("indicators") if isinstance(snapshot.get("indicators"), dict) else {}
    if m == "rsi":
        r = indicators.get("rsi") if isinstance(indicators.get("rsi"), dict) else {}
        val = r.get("rsi")
        return float(val) if isinstance(val, (int, float)) else None
    if m in {"close", "price", "current_price"}:
        val = snapshot.get("current_price")
        return float(val) if isinstance(val, (int, float)) else None
    return None


class InternalAlertEngine:
    def __init__(
        self,
        alerts_config_path: str = "config/alerts.yaml",
        main_config_path: Optional[str] = None,
    ) -> None:
        self.root = Path(__file__).resolve().parents[2]
        self.alerts_cfg = _load_yaml(self.root / alerts_config_path)
        if main_config_path is not None:
            self.main_cfg = _load_yaml(self.root / main_config_path)
        else:
            from src.config_loader import load_system_config

            self.main_cfg = load_system_config(use_cache=True)
        self.indicator_service = IndicatorService()

    def _mode(self) -> str:
        chart_cfg = self.main_cfg.get("internal_chart") or {}
        mode = str(chart_cfg.get("mode", "observe")).strip().lower()
        return mode if mode in {"observe", "semi_auto", "auto"} else "observe"

    def _enabled(self) -> bool:
        chart_cfg = self.main_cfg.get("internal_chart") or {}
        return bool(chart_cfg.get("enabled", False))

    def _event_store_path(self) -> Path:
        p = (
            self.alerts_cfg.get("alert_engine", {})
            .get("store", {})
            .get("path", "data/alerts/internal_alert_events.jsonl")
        )
        return self.root / str(p)

    def _load_rules(self) -> Tuple[List[AlertRule], List[str]]:
        rules = self.alerts_cfg.get("rules")
        if not isinstance(rules, list):
            # Built-in minimal defaults for MVP if rules are not configured yet.
            rules = [
                {
                    "rule_id": "rsi_oversold_510300_30m",
                    "contract_version": "1.0",
                    "enabled": True,
                    "symbol": "510300",
                    "timeframe": "30m",
                    "group": "technical",
                    "priority": "medium",
                    "condition": {"type": "threshold", "metric": "rsi", "operator": "<=", "value": 30},
                    "cooldown_sec": 300,
                    "ttl_sec": 86400,
                    "notify": {"channels": ["feishu"]},
                    "actions": {"emit_signal_candidate": True},
                }
            ]

        parsed: List[AlertRule] = []
        errors: List[str] = []
        for idx, raw in enumerate(rules):
            if not isinstance(raw, dict):
                errors.append(f"rules[{idx}] is not object")
                continue
            val_errors = validate_rule_obj(raw)
            if val_errors:
                errors.extend([f"rules[{idx}]: {e}" for e in val_errors])
                continue
            parsed.append(parse_rule(raw))
        return parsed, errors

    def _read_events(self) -> List[Dict[str, Any]]:
        p = self._event_store_path()
        if not p.is_file():
            return []
        rows: List[Dict[str, Any]] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except json.JSONDecodeError:
                continue
        return rows

    def _write_event(self, event: Dict[str, Any]) -> None:
        p = self._event_store_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _is_dedup_or_cooldown(self, rule: AlertRule, dedup_key: str, now: datetime) -> Tuple[bool, str]:
        rows = self._read_events()
        for row in reversed(rows):
            if row.get("dedup_key") == dedup_key:
                return True, "dedup_skipped"
            if row.get("rule_id") == rule.rule_id and row.get("symbol") == rule.symbol and row.get("status") == "triggered":
                ts_raw = row.get("trigger_ts")
                if isinstance(ts_raw, str):
                    try:
                        ts = datetime.fromisoformat(ts_raw)
                        if now - ts <= timedelta(seconds=rule.cooldown_sec):
                            return True, "cooldown_skipped"
                    except ValueError:
                        pass
                break
        return False, "triggered"

    def run_scan(self, symbols: List[str] | None = None) -> Dict[str, Any]:
        if not self._enabled():
            return {"success": True, "message": "internal_chart disabled", "data": {"events": [], "mode": self._mode()}}

        rules, rule_errors = self._load_rules()
        if rule_errors:
            return {"success": False, "message": "rule validation failed", "data": {"errors": rule_errors}}

        target_symbols = set(symbols or [])
        now = _now_shanghai()
        events: List[Dict[str, Any]] = []

        for rule in rules:
            if not rule.enabled:
                continue
            if target_symbols and rule.symbol not in target_symbols:
                continue
            snapshot_resp = self.indicator_service.calculate(
                symbol=rule.symbol,
                data_type="etf_daily",
                indicators=["rsi", "ma", "macd", "bollinger"],
                lookback_days=180,
            )
            if not snapshot_resp.get("success"):
                continue
            snapshot = snapshot_resp.get("data") or {}
            actual = _extract_metric(snapshot, rule.condition.metric)
            if actual is None:
                continue
            matched = _compare(rule.condition.operator, actual, rule.condition.value)
            if not matched:
                continue

            bar_ts = now.replace(second=0, microsecond=0).isoformat()
            dedup_key = f"internal_chart_alert|{rule.symbol}|{rule.timeframe}|{rule.rule_id}|{bar_ts}"
            blocked, status = self._is_dedup_or_cooldown(rule, dedup_key, now)
            event = {
                "event_id": f"evt_{now.strftime('%Y%m%d_%H%M%S')}_{rule.symbol}_{rule.rule_id}",
                "contract_version": rule.contract_version,
                "source": "internal_chart_alert",
                "rule_id": rule.rule_id,
                "symbol": rule.symbol,
                "timeframe": rule.timeframe,
                "trigger_ts": now.isoformat(),
                "bar_ts": bar_ts,
                "group": rule.group,
                "priority": rule.priority,
                "condition_snapshot": {
                    "metric": rule.condition.metric,
                    "operator": rule.condition.operator,
                    "value": rule.condition.value,
                    "actual": actual,
                },
                "dedup_key": dedup_key,
                "status": status,
                "metadata": {
                    "mode": self._mode(),
                    "rule": asdict(rule),
                },
            }
            self._write_event(event)
            events.append(event)

            if not blocked:
                tool_send_signal_alert(
                    signal_data={
                        "signal_type": "internal_chart_alert",
                        "signal_strength": "medium",
                        "underlying": rule.symbol,
                        "rule_id": rule.rule_id,
                        "group": rule.group,
                        "priority": rule.priority,
                        "condition_snapshot": event["condition_snapshot"],
                    },
                    min_signal_strength="medium",
                    mode="test" if self._mode() == "observe" else "prod",
                )

        return {
            "success": True,
            "message": f"scan completed: {len(events)} events",
            "data": {"mode": self._mode(), "events": events},
        }


def tool_internal_alert_scan(symbols: str = "") -> Dict[str, Any]:
    target = [x.strip() for x in symbols.split(",") if x.strip()] if symbols else []
    engine = InternalAlertEngine()
    return engine.run_scan(target or None)

