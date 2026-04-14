from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.backtest_service import BacktestConfig, BacktestService


def _read_jsonl(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except json.JSONDecodeError:
            continue
    return pd.DataFrame(rows)


def main() -> None:
    st.set_page_config(page_title="Backtest & Quality", layout="wide")
    st.title("Internal Alert Quality Backtest (Pro)")
    st.sidebar.subheader("Navigation")
    st.sidebar.page_link("app.py", label="Chart Console", icon=":material/candlestick_chart:")
    st.sidebar.page_link("pages/backtest.py", label="Backtest & Quality", icon=":material/monitoring:")
    st.sidebar.page_link("pages/rules_config.py", label="Rules Config", icon=":material/tune:")
    st.sidebar.page_link("pages/alert_replay.py", label="Alert Replay", icon=":material/history:")

    st.subheader("Strategy Research")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        symbol = st.selectbox("Symbol", ["510300", "510500", "510050"], index=0)
    with c2:
        fast_ma = st.number_input("Fast MA", min_value=3, max_value=60, value=10, step=1)
    with c3:
        slow_ma = st.number_input("Slow MA", min_value=5, max_value=180, value=30, step=1)
    with c4:
        lookback = st.number_input("Lookback Days", min_value=60, max_value=500, value=240, step=10)
    run = st.button("Run Backtest", type="primary")

    if run:
        svc = BacktestService()
        resp = svc.run_ma_crossover(
            BacktestConfig(symbol=symbol, lookback_days=int(lookback), fast_ma=int(fast_ma), slow_ma=int(slow_ma))
        )
        if not resp.get("success"):
            st.error(resp.get("message", "backtest failed"))
        else:
            data = resp["data"]
            metrics = data["metrics"]
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Strategy Return", f"{metrics['total_return']:.2%}")
            m2.metric("Benchmark Return", f"{metrics['benchmark_return']:.2%}")
            m3.metric("Max Drawdown", f"{metrics['max_drawdown']:.2%}")
            m4.metric("Trade Count", metrics["trade_count"])
            m5.metric("Win Rate", f"{metrics['win_rate']:.2%}")

            series = data["series"]
            fig = go.Figure()
            fig.add_scatter(x=series["datetime"], y=series["equity"], mode="lines", name="Strategy Equity")
            fig.add_scatter(x=series["datetime"], y=series["benchmark"], mode="lines", name="Benchmark")
            entries = series[series["trade_flag"] > 0]
            fig.add_scatter(
                x=entries["datetime"],
                y=entries["equity"],
                mode="markers",
                marker={"size": 8},
                name="Trade Signal",
            )
            fig.update_layout(template="plotly_white", title="Strategy vs Benchmark")
            st.plotly_chart(fig, width="stretch")
            st.caption(f"Data source: {(data.get('cache_status') or {}).get('source', 'unknown')}")
            st.dataframe(series.tail(80), width="stretch")

    st.markdown("---")

    events_path = ROOT / "data" / "alerts" / "internal_alert_events.jsonl"
    df = _read_jsonl(events_path)
    if df.empty:
        st.info("No internal alert events yet.")
        return

    st.subheader("Core Metrics")
    total = len(df)
    triggered = len(df[df.get("status") == "triggered"]) if "status" in df.columns else 0
    skipped = total - triggered
    noise_ratio = round(skipped / total, 4) if total else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Events", total)
    c2.metric("Triggered", triggered)
    c3.metric("Noise Ratio", noise_ratio)

    if "trigger_ts" in df.columns:
        df["trigger_ts"] = pd.to_datetime(df["trigger_ts"], errors="coerce")
        times = df.dropna(subset=["trigger_ts"]).sort_values("trigger_ts")
        if not times.empty:
            daily = times.groupby(times["trigger_ts"].dt.date).size().reset_index(name="count")
            fig = px.line(daily, x="trigger_ts", y="count", title="Daily Internal Alert Count")
            st.plotly_chart(fig, width="stretch")

    st.subheader("Group / Priority Distribution")
    if "group" in df.columns:
        st.bar_chart(df["group"].value_counts())
    if "priority" in df.columns:
        st.bar_chart(df["priority"].value_counts())

    st.subheader("Raw Event Sample")
    st.dataframe(df.tail(100), width="stretch")


if __name__ == "__main__":
    main()

