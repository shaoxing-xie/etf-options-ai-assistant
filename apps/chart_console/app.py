from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.indicator_service import IndicatorService
from src.services.market_data_service import MarketDataService
from src.services.workspace_service import WorkspaceService


def _source_badge(source: str) -> tuple[str, str]:
    mapping = {
        "cache": ("green", "缓存命中"),
        "cache+data_collection_historical": ("orange", "缓存命中(字段补拉)"),
        "local_csv": ("yellow", "本地CSV回退"),
        "data_collection_historical": ("orange", "采集插件回退"),
        "merged_historical": ("red", "合并工具回退"),
    }
    color, label = mapping.get(source, ("gray", "未知来源"))
    return color, label


def _build_candles(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.56, 0.14, 0.15, 0.15],
    )
    fig.add_trace(
        go.Candlestick(
            x=df["datetime"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="OHLC",
        ),
        row=1,
        col=1,
    )
    if "volume" in df.columns:
        fig.add_trace(
            go.Bar(x=df["datetime"], y=df["volume"], name="Volume", opacity=0.4),
            row=2,
            col=1,
        )
    fig.update_layout(
        title="Internal Chart Console Pro",
        xaxis_rangeslider_visible=False,
        dragmode="pan",
        hovermode="x unified",
        template="plotly_white",
        legend_orientation="h",
        legend_y=1.02,
        legend_x=0,
        uirevision="chart-console",
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    fig.update_yaxes(title_text="MACD", row=3, col=1)
    fig.update_yaxes(title_text="RSI", row=4, col=1, range=[0, 100])
    return fig


def _add_ma(fig: go.Figure, df: pd.DataFrame, periods: list[int]) -> None:
    for p in periods:
        ma = df["close"].rolling(window=p, min_periods=max(2, p // 2)).mean()
        fig.add_scatter(x=df["datetime"], y=ma, mode="lines", name=f"MA{p}", row=1, col=1)


def _add_indicator_panes(fig: go.Figure, df: pd.DataFrame, ind_data: dict[str, Any]) -> None:
    indicators = ind_data.get("indicators", {}) if isinstance(ind_data, dict) else {}
    macd = indicators.get("macd", {}) if isinstance(indicators, dict) else {}
    rsi = indicators.get("rsi", {}) if isinstance(indicators, dict) else {}
    boll = indicators.get("bollinger", {}) if isinstance(indicators, dict) else {}

    if isinstance(macd, dict):
        hist = pd.to_numeric(pd.Series(macd.get("hist", [])), errors="coerce")
        dif = pd.to_numeric(pd.Series(macd.get("dif", [])), errors="coerce")
        dea = pd.to_numeric(pd.Series(macd.get("dea", [])), errors="coerce")
        n = min(len(df), len(hist), len(dif), len(dea))
        if n > 0:
            x = df["datetime"].tail(n)
            fig.add_trace(go.Bar(x=x, y=hist.tail(n), name="MACD Hist", opacity=0.45), row=3, col=1)
            fig.add_trace(go.Scatter(x=x, y=dif.tail(n), name="DIF"), row=3, col=1)
            fig.add_trace(go.Scatter(x=x, y=dea.tail(n), name="DEA"), row=3, col=1)

    if isinstance(rsi, dict):
        values = pd.to_numeric(pd.Series(rsi.get("values", [])), errors="coerce")
        n = min(len(df), len(values))
        if n > 0:
            x = df["datetime"].tail(n)
            fig.add_trace(go.Scatter(x=x, y=values.tail(n), name="RSI"), row=4, col=1)
            fig.add_hline(y=30, line_dash="dot", row=4, col=1)
            fig.add_hline(y=70, line_dash="dot", row=4, col=1)

    if isinstance(boll, dict):
        upper = pd.to_numeric(pd.Series(boll.get("upper", [])), errors="coerce")
        mid = pd.to_numeric(pd.Series(boll.get("middle", [])), errors="coerce")
        lower = pd.to_numeric(pd.Series(boll.get("lower", [])), errors="coerce")
        n = min(len(df), len(upper), len(mid), len(lower))
        if n > 0:
            x = df["datetime"].tail(n)
            fig.add_trace(go.Scatter(x=x, y=upper.tail(n), name="BOLL U", line={"dash": "dot"}), row=1, col=1)
            fig.add_trace(go.Scatter(x=x, y=mid.tail(n), name="BOLL M"), row=1, col=1)
            fig.add_trace(go.Scatter(x=x, y=lower.tail(n), name="BOLL L", line={"dash": "dot"}), row=1, col=1)


def _apply_draw_objects(fig: go.Figure, draw_objects: list[dict[str, Any]]) -> None:
    for obj in draw_objects:
        kind = str(obj.get("type", "line"))
        if kind == "line":
            fig.add_shape(
                type="line",
                x0=obj.get("x0"),
                y0=obj.get("y0"),
                x1=obj.get("x1"),
                y1=obj.get("y1"),
                line={"width": 2},
                row=1,
                col=1,
            )
        elif kind == "rect":
            fig.add_shape(
                type="rect",
                x0=obj.get("x0"),
                y0=obj.get("y0"),
                x1=obj.get("x1"),
                y1=obj.get("y1"),
                opacity=0.2,
                row=1,
                col=1,
            )
        elif kind == "hline":
            y = obj.get("y", 0)
            fig.add_hline(y=y, row=1, col=1)
        elif kind == "text":
            fig.add_annotation(
                x=obj.get("x0"),
                y=obj.get("y0"),
                text=str(obj.get("text", "")),
                showarrow=True,
                row=1,
                col=1,
            )


def main() -> None:
    st.set_page_config(page_title="Chart Console", layout="wide")
    st.title("OpenClaw Internal Chart Console (Legacy Fallback)")
    st.sidebar.subheader("Navigation")
    st.sidebar.page_link("app.py", label="Chart Console", icon=":material/candlestick_chart:")
    st.sidebar.page_link("pages/backtest.py", label="Backtest & Quality", icon=":material/monitoring:")
    st.sidebar.page_link("pages/rules_config.py", label="Rules Config", icon=":material/tune:")
    st.sidebar.page_link("pages/alert_replay.py", label="Alert Replay", icon=":material/history:")

    symbols = ["510300", "510500", "510050"]
    timeframe_options = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": None}
    ws = WorkspaceService()
    workspaces = ws.list_workspaces()

    col1, col2, col3, col4 = st.columns([1, 1, 2, 2])
    with col1:
        symbol = st.selectbox("Symbol", symbols, index=0)
    with col2:
        lookback = st.slider("Lookback Days", min_value=60, max_value=400, value=180, step=10)
    with col3:
        ma_periods = st.multiselect("MA Periods", [5, 10, 20, 60, 120], default=[5, 10, 20, 60])
    with col4:
        timeframe = st.selectbox("Timeframe", list(timeframe_options.keys()), index=2)

    st.subheader("Workspace")
    w1, w2, w3 = st.columns([2, 1, 1])
    with w1:
        ws_name = st.text_input("Workspace Name", value=f"{symbol}-{timeframe}")
    with w2:
        ws_pick = st.selectbox("Load Workspace", ["(none)"] + [w.get("name", "") for w in workspaces])
    with w3:
        if st.button("Load"):
            selected = ws.get_workspace(ws_pick) if ws_pick != "(none)" else None
            if selected and isinstance(selected.get("state"), dict):
                st.session_state["workspace_state"] = selected["state"]
                st.success(f"Loaded workspace: {ws_pick}")
                st.rerun()

    mkt = MarketDataService()
    ind = IndicatorService()

    data_resp = mkt.get_ohlcv(symbol=symbol, data_type="etf_daily", lookback_days=lookback)
    if not data_resp["success"] or data_resp["data"] is None:
        st.error(data_resp.get("message", "failed to load data"))
        return
    df = data_resp["data"]
    if df.empty:
        st.warning("No data available.")
        return
    required_cols = {"datetime", "open", "high", "low", "close"}
    missing = sorted(required_cols.difference(set(df.columns)))
    if missing:
        st.error(f"Data missing required OHLC columns: {missing}")
        st.caption(f"Available columns: {list(df.columns)}")
        return

    tf_minutes = timeframe_options[timeframe]
    ind_resp = ind.calculate(
        symbol=symbol,
        data_type="etf_daily",
        indicators=["ma", "macd", "rsi", "bollinger"],
        ma_periods=ma_periods,
        lookback_days=lookback,
        timeframe_minutes=tf_minutes,
    )
    fig = _build_candles(df)
    _add_ma(fig, df, ma_periods)
    if ind_resp["success"]:
        _add_indicator_panes(fig, df, ind_resp["data"])

    st.subheader("Drawing Tools")
    draw_key = f"draw_objects::{symbol}::{timeframe}"
    if draw_key not in st.session_state:
        st.session_state[draw_key] = []
    d1, d2, d3, d4, d5 = st.columns([1, 1, 1, 1, 2])
    with d1:
        draw_type = st.selectbox("Type", ["line", "hline", "rect", "text"])
    with d2:
        x0 = st.text_input("x0 (date)", value=str(df["datetime"].iloc[max(0, len(df) - 20)].date()))
    with d3:
        y0 = st.number_input("y0", value=float(df["close"].iloc[-1]))
    with d4:
        y1 = st.number_input("y1", value=float(df["close"].iloc[-1]))
    with d5:
        text_note = st.text_input("text", value="note")
    if st.button("Add Draw Object"):
        item = {"type": draw_type, "x0": x0, "y0": y0, "x1": str(df["datetime"].iloc[-1].date()), "y1": y1, "text": text_note}
        st.session_state[draw_key].append(item)
        st.rerun()
    if st.button("Clear Draw Objects"):
        st.session_state[draw_key] = []
        st.rerun()

    _apply_draw_objects(fig, st.session_state[draw_key])
    st.plotly_chart(
        fig,
        width="stretch",
        config={
            "displaylogo": False,
            "modeBarButtonsToAdd": ["drawline", "drawrect", "drawopenpath", "eraseshape"],
        },
    )

    st.subheader("Indicator Snapshot")
    if ind_resp["success"]:
        st.json(ind_resp["data"])
    else:
        st.error(ind_resp.get("message", "indicator failed"))

    st.subheader("Cache Status")
    cache_status = data_resp.get("cache_status", {})
    source = str(cache_status.get("source", "unknown"))
    color, source_label = _source_badge(source)
    c1, c2 = st.columns([1, 3])
    with c1:
        st.metric("Data Source", source)
        st.markdown(f":{color}[● {source_label}]")
    with c2:
        st.caption(str(cache_status.get("message", "")))
    st.json(cache_status)

    st.subheader("Save Workspace")
    state = {
        "symbol": symbol,
        "timeframe": timeframe,
        "lookback_days": lookback,
        "ma_periods": ma_periods,
        "draw_objects": st.session_state[draw_key],
    }
    s1, s2 = st.columns([1, 1])
    with s1:
        if st.button("Save Workspace", type="primary"):
            ws.save_workspace(ws_name, state)
            st.success(f"Workspace saved: {ws_name}")
    with s2:
        if ws_pick != "(none)" and st.button("Delete Selected Workspace"):
            if ws.delete_workspace(ws_pick):
                st.success(f"Deleted workspace: {ws_pick}")
                st.rerun()

    st.caption(
        "Pro mode includes multi-timeframe controls, pane indicators, drawing object persistence, "
        "cache status lights, and workspace save/load."
    )


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()

