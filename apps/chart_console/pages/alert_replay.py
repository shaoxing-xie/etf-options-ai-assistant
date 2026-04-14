from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read_jsonl(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return pd.DataFrame(rows)


def main() -> None:
    st.set_page_config(page_title="Alert Replay", layout="wide")
    st.title("Internal Alert Replay")
    st.sidebar.subheader("Navigation")
    st.sidebar.page_link("app.py", label="Chart Console", icon=":material/candlestick_chart:")
    st.sidebar.page_link("pages/backtest.py", label="Backtest & Quality", icon=":material/monitoring:")
    st.sidebar.page_link("pages/rules_config.py", label="Rules Config", icon=":material/tune:")
    st.sidebar.page_link("pages/alert_replay.py", label="Alert Replay", icon=":material/history:")

    events_path = ROOT / "data" / "alerts" / "internal_alert_events.jsonl"
    df = _read_jsonl(events_path)
    if df.empty:
        st.info("No alert events yet. Run `workflows/internal_alert_scan.yaml` first.")
        return

    st.subheader("Status Flow")
    if "status" in df.columns:
        st.bar_chart(df["status"].value_counts())
    if "group" in df.columns:
        st.bar_chart(df["group"].value_counts())

    st.subheader("Replay Filters")
    c1, c2, c3 = st.columns(3)
    with c1:
        symbol = st.selectbox("Symbol", ["(all)"] + sorted(df["symbol"].dropna().astype(str).unique().tolist()))
    with c2:
        status = st.selectbox("Status", ["(all)"] + sorted(df["status"].dropna().astype(str).unique().tolist()))
    with c3:
        rule_id = st.text_input("Rule ID contains", value="")

    out = df.copy()
    if symbol != "(all)":
        out = out[out["symbol"].astype(str) == symbol]
    if status != "(all)":
        out = out[out["status"].astype(str) == status]
    if rule_id.strip():
        out = out[out["rule_id"].astype(str).str.contains(rule_id.strip(), case=False, na=False)]

    if "trigger_ts" in out.columns:
        out["trigger_ts"] = pd.to_datetime(out["trigger_ts"], errors="coerce")
        out = out.sort_values("trigger_ts")
        timeline = out.dropna(subset=["trigger_ts"]).copy()
        if not timeline.empty:
            timeline["count"] = 1
            fig = px.scatter(
                timeline,
                x="trigger_ts",
                y="count",
                color="status" if "status" in timeline.columns else None,
                hover_data=["symbol", "rule_id"] if {"symbol", "rule_id"}.issubset(timeline.columns) else None,
                title="Alert Event Replay Timeline",
            )
            fig.update_layout(template="plotly_white")
            st.plotly_chart(fig, width="stretch")

    st.subheader("Replay Table")
    st.dataframe(out.tail(300), width="stretch")


if __name__ == "__main__":
    main()
