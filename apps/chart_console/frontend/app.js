import { jget, jpost } from "./api.js";
import { initCharts, renderDraw, toTs } from "./charts.js";

function qs(id) {
  return document.getElementById(id);
}

function showBootError(message) {
  const el = qs("bootError");
  if (!el) return;
  el.style.display = "block";
  el.textContent = message;
}

let charts;
try {
  charts = initCharts({ main: "chartMain", macd: "chartMacd", rsi: "chartRsi", second: "chartSecond" });
} catch (err) {
  showBootError(`前端初始化失败: ${err?.message || err}`);
  throw err;
}
const state = { draw_objects: [], layer: { volume: true, macd: true, rsi: true, ma: true } };

function toArrayValues(value) {
  if (Array.isArray(value)) return value;
  if (value && typeof value === "object") {
    if (Array.isArray(value.values)) return value.values;
    if (Array.isArray(value.data)) return value.data;
    const numVals = Object.values(value).filter((v) => typeof v === "number" || (typeof v === "string" && v !== ""));
    if (numVals.length) return numVals;
  }
  if (typeof value === "number") return [value];
  if (typeof value === "string" && value.trim() !== "") return [Number(value)];
  return [];
}

async function loadAlerts() {
  const resp = await jget("/api/alerts/replay");
  const rows = (resp.data || []).slice(-20).reverse();
  const tb = qs("alertTable").querySelector("tbody");
  tb.innerHTML = "";
  for (const x of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${x.trigger_ts || ""}</td><td>${x.symbol || ""}</td><td>${x.status || ""}</td><td>${x.rule_id || ""}</td>`;
    tb.appendChild(tr);
  }
}

async function loadWorkspaces() {
  const resp = await jget("/api/workspaces");
  const pick = qs("wsPick");
  pick.innerHTML = (resp.data || []).map((x) => `<option>${x.name}</option>`).join("");
}

async function loadData() {
  const symbol = qs("symbol").value;
  const tf = qs("tf").value;
  const lookback = qs("lookback").value;
  const ma = qs("ma").value;
  const ohlcv = await jget(`/api/ohlcv?symbol=${symbol}&lookback_days=${lookback}`);
  const bars = (ohlcv.data || []).map((x) => ({
    time: toTs(x.datetime),
    open: Number(x.open),
    high: Number(x.high),
    low: Number(x.low),
    close: Number(x.close),
    volume: Number(x.volume || 0),
  }));

  charts.series.candle.setData(bars);
  charts.series.second.setData(bars.map((b) => ({ time: b.time, value: b.close })));
  if (state.layer.volume) {
    charts.series.vol.setData(
      bars.map((x) => ({ time: x.time, value: x.volume, color: x.close >= x.open ? "#26a69a88" : "#ef535088" })),
    );
  } else {
    charts.series.vol.setData([]);
  }
  charts.mainChart.timeScale().fitContent();

  qs("statusBadge").textContent = `数据源: ${(ohlcv.cache_status || {}).source || "unknown"}`;
  qs("statusBadge").className = `badge ${((ohlcv.cache_status || {}).source || "").includes("cache") ? "ok" : "warn"}`;

  const ind = await jget(
    `/api/indicators?symbol=${symbol}&lookback_days=${lookback}&timeframe_minutes=${tf}&ma_periods=${encodeURIComponent(ma)}`,
  );
  qs("indicatorJson").textContent = JSON.stringify(ind.data || {}, null, 2);
  const indicators = (ind.data || {}).indicators || {};
  const macd = indicators.macd || {};
  const rsi = indicators.rsi || {};
  const n = bars.length;
  const hist = toArrayValues(macd.hist).slice(-n);
  const dif = toArrayValues(macd.dif).slice(-n);
  const dea = toArrayValues(macd.dea).slice(-n);

  charts.series.macdHist.setData(
    state.layer.macd
      ? bars.slice(-hist.length).map((x, i) => ({
          time: x.time,
          value: Number(hist[i] || 0),
          color: Number(hist[i] || 0) >= 0 ? "#26a69a" : "#ef5350",
        }))
      : [],
  );
  charts.series.macdDif.setData(state.layer.macd ? bars.slice(-dif.length).map((x, i) => ({ time: x.time, value: Number(dif[i] || 0) })) : []);
  charts.series.macdDea.setData(state.layer.macd ? bars.slice(-dea.length).map((x, i) => ({ time: x.time, value: Number(dea[i] || 0) })) : []);
  const rsiVals = toArrayValues(rsi.values ?? rsi).slice(-n);
  charts.series.rsi.setData(state.layer.rsi ? bars.slice(-rsiVals.length).map((x, i) => ({ time: x.time, value: Number(rsiVals[i] || 0) })) : []);

  for (const s of charts.series.ma) charts.mainChart.removeSeries(s);
  charts.series.ma.length = 0;
  const maPeriods = ma.split(",").map((x) => Number(x.trim())).filter(Boolean);
  if (state.layer.ma) {
    for (const p of maPeriods) {
      const line = charts.mainChart.addLineSeries({ lineWidth: 1 });
      charts.series.ma.push(line);
      const out = [];
      for (let i = 0; i < bars.length; i++) {
        const start = Math.max(0, i - p + 1);
        const arr = bars.slice(start, i + 1).map((x) => x.close);
        out.push({ time: bars[i].time, value: arr.reduce((a, b) => a + b, 0) / arr.length });
      }
      line.setData(out);
    }
  }
  renderDraw(charts.series, state.draw_objects);
  await loadAlerts();
}

async function runBacktest() {
  const symbol = qs("symbol").value;
  const lookback = qs("lookback").value;
  const fee = qs("feeBps").value;
  const slip = qs("slippageBps").value;
  const resp = await jget(
    `/api/backtest?symbol=${symbol}&lookback_days=${lookback}&fast_ma=10&slow_ma=30&fee_bps=${fee}&slippage_bps=${slip}`,
  );
  qs("backtestJson").textContent = JSON.stringify((resp.data || {}).metrics || resp, null, 2);
}

qs("btnLoad").onclick = loadData;
qs("btnBacktest").onclick = runBacktest;
qs("btnAddDraw").onclick = () => {
  state.draw_objects.push({
    type: qs("drawType").value,
    x0: qs("drawX0").value,
    y0: Number(qs("drawY0").value || 0),
    x1: qs("drawX1").value,
    y1: Number(qs("drawY1").value || 0),
    text: qs("drawText").value,
  });
  renderDraw(charts.series, state.draw_objects);
};
qs("btnClearDraw").onclick = () => {
  state.draw_objects = [];
  renderDraw(charts.series, state.draw_objects);
};

qs("layerVolume").onchange = (e) => {
  state.layer.volume = e.target.checked;
  loadData();
};
qs("layerMacd").onchange = (e) => {
  state.layer.macd = e.target.checked;
  loadData();
};
qs("layerRsi").onchange = (e) => {
  state.layer.rsi = e.target.checked;
  loadData();
};
qs("layerMa").onchange = (e) => {
  state.layer.ma = e.target.checked;
  loadData();
};

qs("btnSaveWs").onclick = async () => {
  const name = qs("wsName").value || "default";
  const payload = {
    symbol: qs("symbol").value,
    timeframe: qs("tf").value,
    lookback_days: Number(qs("lookback").value || 180),
    ma_periods: qs("ma").value.split(",").map((x) => Number(x.trim())).filter(Boolean),
    draw_objects: state.draw_objects,
    layer: state.layer,
  };
  await jpost("/api/workspaces/save", { name, state: payload });
  await jpost("/api/workspace_templates/save", { name: `${name}-template`, template: { ma_periods: payload.ma_periods, layer: payload.layer } });
  await loadWorkspaces();
};
qs("btnLoadWs").onclick = async () => {
  const resp = await jget("/api/workspaces");
  const one = (resp.data || []).find((x) => x.name === qs("wsPick").value);
  if (!one || !one.state) return;
  const ws = one.state;
  qs("symbol").value = ws.symbol || qs("symbol").value;
  qs("tf").value = ws.timeframe || qs("tf").value;
  qs("lookback").value = ws.lookback_days || qs("lookback").value;
  qs("ma").value = (ws.ma_periods || [5, 10, 20, 60]).join(",");
  state.draw_objects = ws.draw_objects || [];
  state.layer = ws.layer || state.layer;
  qs("layerVolume").checked = !!state.layer.volume;
  qs("layerMacd").checked = !!state.layer.macd;
  qs("layerRsi").checked = !!state.layer.rsi;
  qs("layerMa").checked = !!state.layer.ma;
  await loadData();
};
qs("btnDeleteWs").onclick = async () => {
  await jpost("/api/workspaces/delete", { name: qs("wsPick").value });
  await loadWorkspaces();
};

loadWorkspaces().then(loadData).catch((err) => {
  showBootError(`数据加载失败: ${err?.message || err}`);
});
