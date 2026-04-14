from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Any

import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALERTS_PATH = ROOT / "config" / "alerts.yaml"


def _load_alerts_config() -> dict[str, Any]:
    if not ALERTS_PATH.is_file():
        return {}
    try:
        data = yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _save_alerts_config(data: dict[str, Any]) -> None:
    # Keep an on-disk backup for quick rollback from accidental edits.
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ALERTS_PATH.with_name(f"alerts.yaml.bak.{ts}")
    if ALERTS_PATH.exists():
        backup.write_text(ALERTS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    ALERTS_PATH.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _rule_to_row(rule: dict[str, Any]) -> dict[str, Any]:
    cond = rule.get("condition", {}) if isinstance(rule.get("condition"), dict) else {}
    return {
        "enabled": bool(rule.get("enabled", True)),
        "rule_id": str(rule.get("rule_id", "")),
        "symbol": str(rule.get("symbol", "")),
        "timeframe": str(rule.get("timeframe", "30m")),
        "group": str(rule.get("group", "technical")),
        "priority": str(rule.get("priority", "medium")),
        "metric": str(cond.get("metric", "rsi")),
        "operator": str(cond.get("operator", "<=")),
        "value": cond.get("value", 30),
        "cooldown_sec": int(rule.get("cooldown_sec", 600)),
    }


def _row_to_rule(row: dict[str, Any], old_rule: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(old_rule or {})
    base["contract_version"] = str(base.get("contract_version", "1.0"))
    base["enabled"] = bool(row.get("enabled", True))
    base["rule_id"] = str(row.get("rule_id", "")).strip()
    base["symbol"] = str(row.get("symbol", "")).strip()
    base["timeframe"] = str(row.get("timeframe", "30m")).strip()
    base["group"] = str(row.get("group", "technical")).strip()
    base["priority"] = str(row.get("priority", "medium")).strip()
    base["condition"] = {
        "type": "threshold",
        "metric": str(row.get("metric", "rsi")).strip(),
        "operator": str(row.get("operator", "<=")).strip(),
        "value": float(row.get("value", 30)),
    }
    base["cooldown_sec"] = int(row.get("cooldown_sec", 600))
    base["ttl_sec"] = int(base.get("ttl_sec", 86400))
    if not isinstance(base.get("notify"), dict):
        base["notify"] = {"channels": ["feishu"], "template": "default"}
    if not isinstance(base.get("actions"), dict):
        base["actions"] = {"emit_signal_candidate": True}
    if not isinstance(base.get("metadata"), dict):
        base["metadata"] = {"owner": "analysis_team", "tags": ["web_config"]}
    return base


def main() -> None:
    st.set_page_config(page_title="Rules Config", layout="wide")
    st.title("Internal Alert Rules Config")
    st.caption("对标 TradingView 的告警管理：在 Web 上查看、编辑、启停并保存规则。")

    st.sidebar.subheader("Navigation")
    st.sidebar.page_link("app.py", label="Chart Console", icon=":material/candlestick_chart:")
    st.sidebar.page_link("pages/backtest.py", label="Backtest & Quality", icon=":material/monitoring:")
    st.sidebar.page_link("pages/rules_config.py", label="Rules Config", icon=":material/tune:")
    st.sidebar.page_link("pages/alert_replay.py", label="Alert Replay", icon=":material/history:")

    config = _load_alerts_config()
    rules = config.get("rules", [])
    if not isinstance(rules, list):
        rules = []

    rows = [_rule_to_row(r) for r in rules if isinstance(r, dict)]
    table = pd.DataFrame(rows)
    if table.empty:
        table = pd.DataFrame(
            [
                {
                    "enabled": True,
                    "rule_id": "",
                    "symbol": "510300",
                    "timeframe": "30m",
                    "group": "technical",
                    "priority": "medium",
                    "metric": "rsi",
                    "operator": "<=",
                    "value": 30.0,
                    "cooldown_sec": 600,
                }
            ]
        )

    st.subheader("Rules Grid")
    edited = st.data_editor(
        table,
        width="stretch",
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "enabled": st.column_config.CheckboxColumn("enabled"),
            "rule_id": st.column_config.TextColumn("rule_id"),
            "symbol": st.column_config.TextColumn("symbol"),
            "timeframe": st.column_config.SelectboxColumn("timeframe", options=["5m", "15m", "30m", "60m", "1d"]),
            "group": st.column_config.SelectboxColumn("group", options=["technical", "volatility", "regime"]),
            "priority": st.column_config.SelectboxColumn("priority", options=["high", "medium", "low"]),
            "metric": st.column_config.SelectboxColumn("metric", options=["rsi", "current_price", "close", "price"]),
            "operator": st.column_config.SelectboxColumn("operator", options=["<=", "<", ">=", ">", "=="]),
            "value": st.column_config.NumberColumn("value", format="%.4f"),
            "cooldown_sec": st.column_config.NumberColumn("cooldown_sec", min_value=0, step=60),
        },
    )

    c1, c2 = st.columns([1, 3])
    with c1:
        save_clicked = st.button("Save to config/alerts.yaml", type="primary")
    with c2:
        st.caption("保存时会自动生成 alerts.yaml.bak.<timestamp> 备份文件。")

    if save_clicked:
        clean_rows = []
        id_set: set[str] = set()
        for row in edited.to_dict(orient="records"):
            if not str(row.get("rule_id", "")).strip():
                continue
            rid = str(row["rule_id"]).strip()
            if rid in id_set:
                st.error(f"rule_id 重复: {rid}")
                return
            id_set.add(rid)
            if not str(row.get("symbol", "")).strip():
                st.error(f"rule_id={rid} 缺少 symbol")
                return
            clean_rows.append(row)

        old_rules = [r for r in rules if isinstance(r, dict)]
        old_map = {str(r.get("rule_id", "")): r for r in old_rules}
        new_rules = [_row_to_rule(r, old_map.get(str(r.get("rule_id", "")).strip())) for r in clean_rows]

        config["rules"] = new_rules
        _save_alerts_config(config)
        st.success(f"已保存 {len(new_rules)} 条规则到 {ALERTS_PATH}")

    st.markdown("---")
    st.subheader("Quick Add (single rule)")
    with st.form("quick_add_rule"):
        q_rule_id = st.text_input("rule_id", value="")
        q_symbol = st.selectbox("symbol", options=["510300", "510050", "510500"], index=0)
        q_metric = st.selectbox("metric", options=["rsi", "current_price"], index=0)
        q_operator = st.selectbox("operator", options=["<=", "<", ">=", ">", "=="], index=0)
        q_value = st.number_input("value", value=30.0, step=1.0)
        q_priority = st.selectbox("priority", options=["high", "medium", "low"], index=1)
        q_submit = st.form_submit_button("Add Rule")

    if q_submit:
        if not q_rule_id.strip():
            st.error("rule_id 不能为空")
            return
        existing_ids = {str(r.get("rule_id", "")) for r in rules if isinstance(r, dict)}
        if q_rule_id.strip() in existing_ids:
            st.error(f"rule_id 已存在: {q_rule_id.strip()}")
            return
        new_rule = _row_to_rule(
            {
                "enabled": True,
                "rule_id": q_rule_id.strip(),
                "symbol": q_symbol,
                "timeframe": "30m",
                "group": "technical",
                "priority": q_priority,
                "metric": q_metric,
                "operator": q_operator,
                "value": q_value,
                "cooldown_sec": 600,
            }
        )
        config["rules"] = rules + [new_rule]
        _save_alerts_config(config)
        st.success(f"已新增规则: {q_rule_id.strip()} (请刷新页面查看)")


if __name__ == "__main__":
    main()
