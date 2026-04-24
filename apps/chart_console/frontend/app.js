import { jget, jpost } from "./api.js";
import { applyScreeningDayMarker, initCharts, renderDraw, toTs } from "./charts.js";

function qs(id) {
  return document.getElementById(id);
}

function setView(view) {
  const chart = qs("view-chart");
  const config = qs("view-config");
  const screening = qs("view-screening");
  const research = qs("view-research");
  const ops = qs("view-ops");
  if (chart) chart.classList.toggle("active", view === "chart");
  if (config) config.classList.toggle("active", view === "config");
  if (screening) screening.classList.toggle("active", view === "screening");
  if (research) research.classList.toggle("active", view === "research");
  if (ops) ops.classList.toggle("active", view === "ops");
  const tabChart = qs("tab-chart");
  const tabConfig = qs("tab-config");
  const tabScreening = qs("tab-screening");
  const tabResearch = qs("tab-research");
  const tabOps = qs("tab-ops");
  if (tabChart) tabChart.setAttribute("aria-selected", String(view === "chart"));
  if (tabConfig) tabConfig.setAttribute("aria-selected", String(view === "config"));
  if (tabScreening) tabScreening.setAttribute("aria-selected", String(view === "screening"));
  if (tabResearch) tabResearch.setAttribute("aria-selected", String(view === "research"));
  if (tabOps) tabOps.setAttribute("aria-selected", String(view === "ops"));
}

function setConfigSubview(name) {
  const market = qs("config-market");
  const analytics = qs("config-analytics");
  const rotation = qs("config-rotation");
  const isMarket = name === "market";
  const isAnalytics = name === "analytics";
  const isRotation = name === "rotation";
  if (market) market.classList.toggle("active", isMarket);
  if (analytics) analytics.classList.toggle("active", isAnalytics);
  if (rotation) rotation.classList.toggle("active", isRotation);
  const t1 = qs("subtab-market");
  const t2 = qs("subtab-analytics");
  const t3 = qs("subtab-rotation");
  if (t1) t1.setAttribute("aria-selected", String(isMarket));
  if (t2) t2.setAttribute("aria-selected", String(isAnalytics));
  if (t3) t3.setAttribute("aria-selected", String(isRotation));
}

function showBootError(message) {
  const el = qs("bootError");
  if (!el) return;
  el.style.display = "block";
  el.textContent = message;
}

function safeJsonParse(text) {
  try {
    return { ok: true, data: JSON.parse(text) };
  } catch (e) {
    return { ok: false, error: e?.message || String(e) };
  }
}

let charts;
try {
  charts = initCharts({ main: "chartMain", macd: "chartMacd", rsi: "chartRsi", second: "chartSecond" });
} catch (err) {
  showBootError(`前端初始化失败: ${err?.message || err}`);
  // 图表引擎失败时，仍允许使用配置中心
  charts = null;
}
const state = {
  draw_objects: [],
  layer: { volume: true, macd: true, rsi: true, ma: true },
  /** YYYY-MM-DD，来自震荡市选股下钻时在 K 线上标注入选日 */
  screeningEntryDate: null,
};

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

/** 首页「图形」即显示情绪摘要（完整字段在「投研中心」展示） */
async function loadChartSentimentBar() {
  const el = qs("chartSentimentBar");
  if (!el) return;
  try {
    const r = await jget("/api/screening/summary");
    const snap = (r.data && r.data.sentiment_snapshot) || {};
    const keys = Object.keys(snap).filter((k) => k !== "note");
    el.style.display = "block";
    if (!keys.length) {
      el.innerHTML =
        '<span class="warn">市场情绪摘要</span>：暂无落盘（需 <code>data/sentiment_check/*.json</code> 等）。请打开 <strong>投研中心</strong> 查看说明，或设置环境变量 <code>ETF_OPTIONS_ASSISTANT_ROOT</code> 指向含数据的仓库根后重启本服务。';
      return;
    }
    const score = snap.overall_score != null ? String(snap.overall_score) : "—";
    const stage = snap.sentiment_stage != null ? String(snap.sentiment_stage) : "—";
    const pd = snap.precheck_date ? ` · 侧车 <code>${snap.precheck_date}</code>` : "";
    el.innerHTML = `<strong>市场情绪摘要</strong>：综合得分 ${score} · 阶段 ${stage}${pd} · 完整字段见顶部 <strong>投研中心</strong>。`;
  } catch (e) {
    el.style.display = "block";
    el.innerHTML = `市场情绪摘要加载失败：${String(e?.message || e)}`;
  }
}

/**
 * @param {string} symbol
 * @param {{ screeningDate?: string, clearScreeningMarker?: boolean }} [opts]
 */
export async function loadChartForSymbol(symbol, opts = {}) {
  const sel = qs("symbol");
  if (!sel) return;
  const sym = String(symbol || "").trim();
  if (!sym) return;
  if (opts.clearScreeningMarker) {
    state.screeningEntryDate = null;
  } else if (opts.screeningDate) {
    state.screeningEntryDate = String(opts.screeningDate).slice(0, 10);
  }
  const exists = Array.from(sel.options).some((o) => o.value === sym);
  if (!exists) {
    const opt = document.createElement("option");
    opt.value = sym;
    opt.textContent = sym;
    sel.appendChild(opt);
  }
  sel.value = sym;
  setView("chart");
  await loadData();
}

async function loadData() {
  const symbol = qs("symbol").value;
  const tf = qs("tf").value;
  const lookback = qs("lookback").value;
  const ma = qs("ma").value;
  if (!charts) throw new Error("chart renderer unavailable");
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
  applyScreeningDayMarker(charts.series.candle, bars, state.screeningEntryDate);
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

qs("btnLoad").onclick = async () => {
  state.screeningEntryDate = null;
  await loadData();
};
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
  state.screeningEntryDate = null;
  await loadData();
};
qs("btnDeleteWs").onclick = async () => {
  await jpost("/api/workspaces/delete", { name: qs("wsPick").value });
  await loadWorkspaces();
};

// ============ 配置中心 ============
function yamlApi() {
  const api = globalThis.jsyaml;
  if (!api) throw new Error("js-yaml 未加载（请检查网络/CDN）");
  return api;
}

function clearNode(node) {
  if (!node) return;
  while (node.firstChild) node.removeChild(node.firstChild);
}

function renderYamlCards(params) {
  const { container, doc, docsByKey } = params;
  clearNode(container);
  const api = yamlApi();

  const root = doc && typeof doc === "object" && !Array.isArray(doc) ? doc : {};
  const keys = Object.keys(root);
  if (keys.length === 0) {
    const empty = document.createElement("div");
    empty.className = "card";
    empty.innerHTML = `<h4>(empty)</h4><div class="small">该配置文件为空或无法解析为对象。</div>`;
    container.appendChild(empty);
    return;
  }

  for (const key of keys) {
    const card = document.createElement("div");
    card.className = "card";
    const title = document.createElement("h4");
    title.textContent = String(key);
    const desc = document.createElement("div");
    desc.className = "small";
    const hint = (docsByKey && docsByKey[String(key)]) ? String(docsByKey[String(key)]) : "";
    desc.textContent = hint || "（暂无说明）";
    const ta = document.createElement("textarea");
    ta.spellcheck = false;
    ta.dataset.yamlKey = String(key);
    ta.value = api.dump(root[key], { sortKeys: false, lineWidth: 120, noRefs: true });
    card.appendChild(title);
    card.appendChild(desc);
    card.appendChild(ta);
    container.appendChild(card);
  }
}

function enrichedDocsFor(kind) {
  // kind: "market_data" | "analytics"
  if (kind === "market_data") {
    return {
      realtime_full_fetch_cache:
        "用途：控制“全量行情拉取后再筛选”的进程内短缓存（默认 TTL 45s）。\n生效点：`src/realtime_full_fetch_cache.py`（被行情拉取/数据采集路径调用）。\n影响：降低重复网络请求与 API 压力；TTL 过长会导致行情延迟。",
      data_sources:
        "用途：多数据源开关与优先级（ETF分钟/指数分钟/实时股票/全球指数等）。\n生效点：`src/data_collector.py` 多处读取 `data_sources.*` 并按 `priority` 顺序选择 provider。\n影响：决定每类数据优先用哪个 provider、失败重试/熔断策略是否开启。",
      tushare:
        "用途：Tushare 数据源开关与 Token（含是否偏好分钟级）。\n生效点：`src/tushare_fallback.py`、`src/data_collector.py` 等会读取合并配置的 tushare 段。\n影响：当主数据源缺失/失败时的回退能力与稳定性。",
      iopv_fallback:
        "用途：IOPV 缺失时的兜底策略（手工覆盖 / 估算）。\n生效点：`plugins/notification/run_tail_session_analysis.py` 读取 `iopv_fallback.manual_iopv_overrides`，并按 `updated_date==当日` 才启用；可选 estimation 也在同模块使用。\n影响：尾盘/巡检类报告中的 IOPV、溢价率计算口径与风控闸门触发。",
      wide_inspection_overnight_refs:
        "用途：宽基巡检“隔夜参考变量”的可用性开关与降级口径。\n生效点：用于风控/巡检类工作流（相关实现会读取该段决定是否采集某些隔夜变量）。\n影响：当外部参考缺失时，报告会降级并提示原因。",
    };
  }
  if (kind === "analytics") {
    return {
      technical_indicators:
        "用途：技术指标参数总控（MA 周期、MACD/RSI/BOLL/KDJ 等）。\n生效点：指标计算工具链（`plugins.analysis.technical_indicators`）与服务层 `src/services/indicator_service.py`。\n影响：图形工作台指标输出、告警条件计算口径。",
      historical_snapshot:
        "用途：历史快照/面板类分析的窗口与容量控制（默认窗口、最大标的数、波动锥/IV 相关开关）。\n生效点：`src/realized_vol_panel.py` 等会合并并读取该段配置。\n影响：历史统计类输出的取样范围、性能与结果稳定性。",
      volatility_engine:
        "用途：波动率/区间预测引擎的主配置（含 A/B profile、GARCH/IV 融合、成交量修正等）。\n生效点：`src/volatility_range.py` 解析 `volatility_engine.ab_test` 并应用 profile；`src/option_iv_fusion.py` 等读取融合参数。\n影响：波动区间预测的模型选择、权重、置信度与降级/回滚策略。",
    };
  }
  return {};
}

function mergeDocs(params) {
  const { primary, secondary } = params;
  const out = { ...(secondary || {}) };
  for (const [k, v] of Object.entries(primary || {})) {
    const base = String(v || "").trim();
    const extra = String(out[k] || "").trim();
    out[k] = extra ? `${base}\n\n原注释：\n${extra}` : base;
  }
  return out;
}

function extractTopLevelDocs(yamlText) {
  // Extract comment blocks (starting with "#") immediately above a top-level key.
  const text = String(yamlText || "");
  const lines = text.split(/\r?\n/);
  const docs = {};
  let buf = [];

  const flushBuf = () => {
    const out = buf
      .map((l) => l.replace(/^\s*#\s?/, "").trimEnd())
      .filter((x) => x.trim() !== "")
      .join("\n")
      .trim();
    buf = [];
    return out;
  };

  for (const line of lines) {
    // Only consider 0-indent comment lines as section docs.
    if (/^\s*#/.test(line) && !/^\s+/.test(line)) {
      buf.push(line);
      continue;
    }
    // Blank line: keep buffering (allows multi-line comment blocks).
    if (/^\s*$/.test(line)) {
      continue;
    }
    // Top-level key: "foo:" or "foo: value"
    const m = /^([A-Za-z0-9_]+)\s*:\s*(?:#.*)?$/.exec(line);
    if (m) {
      const key = m[1];
      const docText = flushBuf();
      if (docText) docs[key] = docText;
      continue;
    }
    // Any other non-comment content breaks the comment block.
    buf = [];
  }
  return docs;
}

function collectYamlFromCards(container) {
  const api = yamlApi();
  const out = {};
  const inputs = Array.from(container.querySelectorAll("textarea[data-yaml-key]"));
  for (const ta of inputs) {
    const key = ta.dataset.yamlKey;
    const text = String(ta.value || "");
    let val;
    try {
      val = api.load(text);
    } catch (e) {
      throw new Error(`栏目 "${key}" YAML 解析失败: ${e?.message || e}`);
    }
    out[key] = val;
  }
  return api.dump(out, { sortKeys: false, lineWidth: 120, noRefs: true });
}

let marketLoaded = false;
let analyticsLoaded = false;
let rotationLoaded = false;

async function loadMarketConfig() {
  const r = await jget("/api/config/market_data");
  const text = (r.data || {}).text ?? "";
  const api = yamlApi();
  const doc = api.load(String(text || ""));
  const container = qs("marketCards");
  const docsByKey = mergeDocs({
    primary: enrichedDocsFor("market_data"),
    secondary: extractTopLevelDocs(text),
  });
  renderYamlCards({ container, doc, docsByKey });
  marketLoaded = true;
}

async function saveMarketConfig() {
  const container = qs("marketCards");
  const text = collectYamlFromCards(container);
  await jpost("/api/config/market_data/save", { text: String(text ?? "") });
}

async function loadAnalyticsConfig() {
  const r = await jget("/api/config/analytics");
  const text = (r.data || {}).text ?? "";
  const api = yamlApi();
  const doc = api.load(String(text || ""));
  const container = qs("analyticsCards");
  const docsByKey = mergeDocs({
    primary: enrichedDocsFor("analytics"),
    secondary: extractTopLevelDocs(text),
  });
  renderYamlCards({ container, doc, docsByKey });
  analyticsLoaded = true;
}

async function saveAnalyticsConfig() {
  const container = qs("analyticsCards");
  const text = collectYamlFromCards(container);
  await jpost("/api/config/analytics/save", { text: String(text ?? "") });
}

async function loadRotationConfig() {
  const r = await jget("/api/config/rotation");
  const text = (r.data || {}).text ?? "";
  const api = yamlApi();
  const doc = api.load(String(text || ""));
  const container = qs("rotationCards");
  const docsByKey = {
    pool: "初选池与多源合并配置（静态/环境变量/观察池）。",
    three_factor_v2: "三维共振权重与情绪门闸配置。",
    indicator_migration: "评分引擎路由（primary/shadow/rollback）。",
    filters: "基础过滤阈值（相关性/均线/回撤等）。",
  };
  renderYamlCards({ container, doc, docsByKey });
  rotationLoaded = true;
}

async function saveRotationConfig() {
  const container = qs("rotationCards");
  const text = collectYamlFromCards(container);
  await jpost("/api/config/rotation/save", { text: String(text ?? "") });
}

// tab handlers
qs("tab-chart")?.addEventListener("click", () => setView("chart"));
qs("tab-config")?.addEventListener("click", () => setView("config"));

// config subtab handlers
qs("subtab-market")?.addEventListener("click", async () => {
  setConfigSubview("market");
  if (!marketLoaded) await loadMarketConfig();
});
qs("subtab-analytics")?.addEventListener("click", async () => {
  setConfigSubview("analytics");
  if (!analyticsLoaded) await loadAnalyticsConfig();
});
qs("subtab-rotation")?.addEventListener("click", async () => {
  setConfigSubview("rotation");
  if (!rotationLoaded) await loadRotationConfig();
});

qs("btnMarketLoad")?.addEventListener("click", loadMarketConfig);
qs("btnMarketSave")?.addEventListener("click", saveMarketConfig);
qs("btnAnalyticsLoad")?.addEventListener("click", loadAnalyticsConfig);
qs("btnAnalyticsSave")?.addEventListener("click", saveAnalyticsConfig);
qs("btnRotationLoad")?.addEventListener("click", loadRotationConfig);
qs("btnRotationSave")?.addEventListener("click", saveRotationConfig);

export { setView };

// boot
Promise.all([loadWorkspaces(), loadChartSentimentBar()])
  .then(async () => {
    try {
      if (charts) await loadData();
    } catch (e) {
      showBootError(`图表数据加载失败（可切到配置中心继续使用）: ${e?.message || e}`);
      setView("config");
      setConfigSubview("market");
    }
  })
  .catch((err) => {
    showBootError(`启动失败: ${err?.message || err}`);
    setView("config");
    setConfigSubview("market");
  });
