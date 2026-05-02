import { jget, jpost } from "./api.js";
import { loadChartForSymbol, setView } from "./app.js";

function qs(id) {
  return document.getElementById(id);
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function inferColumns(rows) {
  const pref = ["symbol", "name", "score", "composite_score", "quality_score", "rank", "universe", "degraded"];
  const seen = new Set();
  const cols = [];
  for (const k of pref) {
    if (rows.some((r) => r && typeof r === "object" && r[k] !== undefined && r[k] !== null)) {
      cols.push(k);
      seen.add(k);
    }
  }
  for (const r of rows.slice(0, 40)) {
    if (!r || typeof r !== "object") continue;
    for (const k of Object.keys(r)) {
      if (seen.has(k)) continue;
      if (k === "factors" || k === "raw_factors") continue;
      cols.push(k);
      seen.add(k);
      if (cols.length >= 10) break;
    }
    if (cols.length >= 10) break;
  }
  return cols.length ? cols : ["symbol"];
}

function formatCell(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return esc(JSON.stringify(v).slice(0, 120));
  return esc(v);
}

let lastDates = [];
let cachedSummary = null;
let tailCached = null;
let researchCache = { dashboard: {}, view: {}, timeline: [] };
let researchSixIndexSnapshot = {};
let fallbackBannerTimer = null;
const RESEARCH_ALERT_DEFAULTS = {
  hit_rate_5d_pct: { warn_below: 0.45, bad_below: 0.35 },
  pause_events_count: { warn_at_or_above: 2, bad_at_or_above: 4 },
  tail_recommended_count: { warn_at_or_below: 0 },
};
const ROTATION_ETF_NAME_MAP = {
  "510300": "沪深300ETF",
  "510500": "中证500ETF",
  "510050": "上证50ETF",
  "512100": "1000ETF",
  "512480": "半导体ETF",
  "516880": "光伏ETF",
  "515880": "通信ETF",
  "518880": "黄金ETF",
  "588080": "科创50ETF",
  "159915": "创业板ETF",
  "512760": "芯片ETF",
  "515050": "5GETF",
  "159175": "电池ETF",
  "516160": "新能源ETF",
  "159866": "机器人ETF",
  "512710": "军工龙头ETF",
  "516150": "稀土ETF",
  "515790": "光伏ETF",
  "512010": "医药ETF",
  "159928": "消费ETF",
  "159748": "医疗ETF",
  "159819": "农业ETF",
  "512690": "酒ETF",
  "159905": "深红利ETF",
  "159870": "化工ETF",
  "512400": "有色金属ETF",
  "515220": "煤炭ETF",
  "159880": "有色ETF",
  "512000": "券商ETF",
  "512200": "地产ETF",
  "159338": "A500ETF国泰",
  "159361": "A500ETF易方达",
  "513300": "纳斯达克ETF",
  "513130": "恒生科技ETF",
  "513310": "恒生生科ETF",
  "513880": "日经225ETF",
  "515400": "资源ETF",
};
const SIX_INDEX_ORDER = ["000001.SH", "000300.SH", "000688.SH", "399006.SZ", "000905.SH", "000852.SH"];

async function jgetWithFallback(primaryUrl, fallbackUrl) {
  try {
    const r = await jget(primaryUrl);
    if (r && r.success) return r;
    if (!fallbackUrl) return r;
    await recordFallbackEvent(primaryUrl, fallbackUrl, r?.message || "primary_not_success");
  } catch (e) {
    if (!fallbackUrl) throw e;
    await recordFallbackEvent(primaryUrl, fallbackUrl, e?.message || "primary_request_failed");
  }
  showFallbackBanner(primaryUrl, fallbackUrl);
  return jget(fallbackUrl);
}

function showFallbackBanner(primaryUrl, fallbackUrl) {
  const el = qs("researchFallbackBanner");
  if (!el) return;
  if (fallbackBannerTimer) {
    clearTimeout(fallbackBannerTimer);
    fallbackBannerTimer = null;
  }
  el.style.display = "block";
  el.textContent = `已触发兼容兜底：${primaryUrl} -> ${fallbackUrl}`;
  fallbackBannerTimer = setTimeout(() => {
    el.style.display = "none";
  }, 6000);
}

async function recordFallbackEvent(primaryUrl, fallbackUrl, reason) {
  try {
    await jpost("/api/internal/record_fallback", {
      primary_url: primaryUrl,
      fallback_url: fallbackUrl,
      reason: reason || "",
    });
  } catch (_) {
    // ignore fallback recording failures to avoid blocking UI
  }
}

function setScreeningSubview(name) {
  const nightly = qs("screening-nightly");
  const tail = qs("screening-tail");
  const isNightly = name !== "tail";
  if (nightly) nightly.classList.toggle("active", isNightly);
  if (tail) tail.classList.toggle("active", !isNightly);
  const t1 = qs("subtab-screening-nightly");
  const t2 = qs("subtab-screening-tail");
  if (t1) t1.setAttribute("aria-selected", String(isNightly));
  if (t2) t2.setAttribute("aria-selected", String(!isNightly));
}

/** 页顶一句人话说明（对标研究台「当日摘要」） */
const PAGE_INTRO =
  "本页展示的是「周度策略定调 + 夜盘选股审计」在本地仓库中的只读结果，用于对照因子与风控门闸，不是交易指令。数据随夜盘/周度任务自动落盘，刷新即可同步。";

/** regime 内部值 → 中文市场状态（与 strategy-calibration 约定一致） */
const REGIME_LABEL = {
  oscillation: "震荡市",
  trend: "趋势市",
  extreme: "极端波动",
  neutral: "中性",
};

const REGIME_NARRATIVE = {
  oscillation:
    "指数与结构更可能呈区间震荡，策略上侧重反转、波段与质量过滤；若情绪过热/过冷，会配合门闸与熔断提示。",
  trend: "趋势性更强时，动量与趋势类因子权重通常更高；请以当周定调说明为准。",
  extreme: "波动与不确定性偏高，模型可能收紧观察池或提示暂停写入。",
  neutral: "未给出强趋势或强震荡判断时，按默认选股与门禁规则执行。",
};

const SENTIMENT_FIELD_LABEL = {
  composite_score: "综合情绪分",
  sentiment_score: "情绪得分",
  overall_score: "综合得分",
  sentiment_stage: "情绪阶段",
  stage: "情绪阶段",
  sentiment_dispersion: "情绪分歧度",
  regime: "环境标签",
  data_quality: "数据完整度",
  data_completeness_ratio: "数据完整度（0–1）",
  action_bias: "行动倾向",
  confidence_band: "置信区间",
  degraded: "数据是否降级",
  factor_attribution: "因子归因（四工具摘要）",
  precheck_date: "侧车交易日（文件名）",
  note: "备注",
};

const TABLE_COL_LABEL = {
  symbol: "代码",
  name: "名称",
  score: "综合得分",
  composite_score: "综合得分",
  quality_score: "质量分",
  rank: "名次",
  universe: "标的池",
  degraded: "数据降级",
};

function regimeKey(raw) {
  const s = String(raw ?? "").trim().toLowerCase();
  return s || "—";
}

function regimeDisplayLabel(raw) {
  const k = regimeKey(raw);
  if (k === "—") return "未标注";
  return REGIME_LABEL[k] || raw;
}

function regimeNarrativeFor(raw) {
  const k = regimeKey(raw);
  if (k === "—") return "尚未写入周度市场状态，选股仍按默认规则与门禁执行。";
  return REGIME_NARRATIVE[k] || "请以本周策略定调说明与夜盘审计为准。";
}

function formatCalibrationUpdated(wc) {
  const u = wc?.last_updated;
  if (u == null || u === "") return "更新时间未在文件中标注（以任务实际执行时刻为准）。";
  return `文件记录更新：${esc(String(u))}`;
}

function calibrationNotesForHumans(wc) {
  const notes = wc?.notes;
  if (notes == null || String(notes).trim() === "") return "";
  const n = String(notes);
  if (/请勿|OpenClaw|Chart Console|只读/.test(n)) {
    return `<details class="screening-details"><summary>数据来源说明（点击展开）</summary><div class="small" style="margin-top:6px;">${esc(
      n,
    )}</div></details>`;
  }
  return `<div class="small" style="margin-top:8px;line-height:1.45;">${esc(n)}</div>`;
}

function toHumanPct(x) {
  const n = Number(x);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function factorAttributionPrettyHtml(obj) {
  if (!obj || typeof obj !== "object") return "";
  const rows = [];
  const pushRow = (title, items) => {
    const parts = items.filter(Boolean).map((x) => `<span class="screening-factor-pill">${esc(x)}</span>`).join("");
    rows.push(`<div class="screening-factor-row"><span class="screening-factor-k">${esc(title)}</span><span class="screening-factor-v">${parts || "—"}</span></div>`);
  };
  const pick = (k) => (obj && typeof obj === "object" ? obj[k] : null);

  const limitUp = pick("limit_up") || pick("limit_up_stocks");
  if (limitUp && typeof limitUp === "object") {
    pushRow("涨停生态", [
      limitUp.date ? `date=${limitUp.date}` : null,
      limitUp.count != null ? `count=${limitUp.count}` : null,
      limitUp.score != null ? `score=${limitUp.score}` : null,
      limitUp.broken_rate != null ? `破板率=${toHumanPct(limitUp.broken_rate)}` : null,
      limitUp.quality === true ? "quality=OK" : limitUp.quality === false ? "quality=FAIL" : null,
      limitUp.error_code ? `err=${limitUp.error_code}` : null,
    ]);
  }

  const fund = pick("fund_flow") || pick("a_share_fund_flow");
  if (fund && typeof fund === "object") {
    pushRow("资金面", [
      fund.date ? `date=${fund.date}` : null,
      fund.total_net != null ? `净流入=${fund.total_net}` : null,
      fund.positive_ratio != null ? `正比例=${toHumanPct(fund.positive_ratio)}` : null,
      fund.score != null ? `score=${fund.score}` : null,
      fund.quality_score != null ? `quality_score=${fund.quality_score}` : null,
      fund.quality === true ? "quality=OK" : fund.quality === false ? "quality=FAIL" : null,
      fund.error_code ? `err=${fund.error_code}` : null,
    ]);
  }

  const north = pick("northbound") || pick("northbound_flow");
  if (north && typeof north === "object") {
    pushRow("北向资金", [
      north.date ? `data_date=${north.date}` : null,
      north.data_date ? `data_date=${north.data_date}` : null,
      north.total_net != null ? `净流入=${north.total_net}` : null,
      north.signal_strength ? `signal=${north.signal_strength}` : null,
      north.signal && typeof north.signal === "object" && north.signal.strength ? `signal=${north.signal.strength}` : null,
      north.quality === true ? "quality=OK" : north.quality === false ? "quality=FAIL" : null,
      north.error_code ? `err=${north.error_code}` : null,
    ]);
  }

  const sector = pick("sector") || pick("sector_data");
  if (sector && typeof sector === "object") {
    pushRow("板块结构", [
      sector.date ? `date=${sector.date}` : null,
      sector.avg_change != null ? `avg=${sector.avg_change}%` : null,
      sector.max_gain != null ? `max_gain=${sector.max_gain}%` : null,
      sector.rotation_speed ? `rotation=${sector.rotation_speed}` : null,
      sector.quality === true ? "quality=OK" : sector.quality === false ? "quality=FAIL" : null,
      sector.error_code ? `err=${sector.error_code}` : null,
    ]);
  }

  if (!rows.length) return "";
  return `<div class="screening-factor-grid">${rows.join("")}</div>`;
}

function sentimentRowsHtml(sent) {
  const keys = Object.keys(sent || {}).filter((k) => k !== "note");
  if (!keys.length) return "";
  return keys
    .map((k) => {
      const lab = SENTIMENT_FIELD_LABEL[k] || k;
      const v = sent[k];
      let disp;
      if (k === "factor_attribution") {
        disp = factorAttributionPrettyHtml(v) || esc(JSON.stringify(v));
      } else if (typeof v === "object") {
        disp = esc(JSON.stringify(v));
      } else {
        disp = esc(String(v));
      }
      return `<div class="screening-card-kv"><span class="screening-card-title">${esc(lab)}</span><span>${disp}</span></div>`;
    })
    .join("");
}

function emptySentimentHelp() {
  return `
    <p class="screening-muted" style="margin:0 0 6px 0;">当前<strong>没有可展示的市场情绪摘要</strong>（对标卖方常用的「情绪温度计」：把涨跌停、资金面、板块强弱等压成一屏可读分数/阶段）。</p>
    <ul class="screening-help-list small">
      <li><strong>为什么为空</strong>：本页读取 <code>weekly_calibration.json</code>、<code>data/screening/sentiment_context.json</code>，以及 <code>data/sentiment_check/YYYY-MM-DD.json</code>（OpenClaw 任务 <code>pre-market-sentiment-check</code> 侧车）。三者均未落盘时此处为空。</li>
      <li><strong>有数据时您会看到什么</strong>：综合得分、情绪阶段（如偏热/中性/偏冷）、完整度与降级标记等。</li>
      <li><strong>您可以做什么</strong>：确认 09:10 任务已写入 <code>data/sentiment_check/</code> 或夜盘已写入 screening 快照后点击「刷新」。工作区须指向含上述文件的 ETF 仓库根目录。</li>
    </ul>`;
}

function qualityPolicyHuman(pol) {
  if (!pol || typeof pol !== "object") return "未配置质量门槛（请检查 data_quality_policy）。";
  const minQ = pol.min_quality_score;
  const block = pol.block_watchlist_if_degraded;
  const lines = [];
  if (minQ != null) lines.push(`最低数据质量分：<strong>${esc(String(minQ))}</strong>（低于则可能筛掉标的）。`);
  if (block === true) lines.push("若因子数据标记为<strong>降级</strong>，将<strong>拦截</strong>写入观察池。");
  else if (block === false) lines.push("因子数据<strong>降级</strong>时仍可能保留候选（仅提示），具体以夜盘审计为准。");
  if (!lines.length) return "未读取到有效的质量门槛说明（请检查项目内数据质量策略配置）。";
  return lines.join("<br/>");
}

function renderPhaseHint() {
  const el = qs("screeningPhaseHint");
  if (el) el.textContent = PAGE_INTRO;
}

/** 与后端 run_snapshot 字段一致（便于切换日期时仅用 artifact 重算） */
function buildRunSnapshotFromArtifact(art) {
  if (!art || typeof art !== "object") return null;
  const scr = art.screening && typeof art.screening === "object" ? art.screening : {};
  return {
    artifact_run_date: art.run_date,
    artifact_written_at: art.written_at,
    watchlist_merged: !!art.merged_watchlist_path,
    schema_ok: art.schema_ok,
    schema_issues: art.schema_issues,
    pause_active_artifact: art.pause_active,
    watchlist_allowed: art.watchlist_allowed,
    screening_success: scr.success,
    quality_score: scr.quality_score,
    degraded: scr.degraded,
    config_hash: scr.config_hash,
    plugin_version: scr.plugin_version,
    universe: scr.universe,
    regime_hint: scr.regime_hint,
    elapsed_ms: scr.elapsed_ms,
  };
}

function renderRunSnapshot(art) {
  const el = qs("screeningRunSnapshot");
  if (!el) return;
  const snap = art && art.screening ? buildRunSnapshotFromArtifact(art) : cachedSummary?.run_snapshot || null;
  if (!snap || Object.keys(snap).length === 0) {
    el.innerHTML = `<div class="screening-snap-empty small">尚未载入最近一次<strong>夜盘选股审计</strong>。请确认已执行夜盘落盘任务后点击「刷新」。</div>`;
    return;
  }
  const hash = snap.config_hash != null ? String(snap.config_hash) : "—";
  const hashShort = hash.length > 14 ? `${hash.slice(0, 10)}…` : hash;
  const pill = (label, val, warn) =>
    `<div class="screening-snap-pill${warn ? " warn" : ""}"><span class="lbl">${esc(label)}</span><span class="val">${esc(val)}</span></div>`;
  const rows = [
    pill("筛选是否成功", snap.screening_success === true ? "成功" : snap.screening_success === false ? "失败" : "—", snap.screening_success === false),
    pill("数据质量综合分", snap.quality_score != null ? String(snap.quality_score) : "—", false),
    pill("数据是否降级", snap.degraded === true ? "是（需谨慎）" : snap.degraded === false ? "否" : "—", snap.degraded === true),
    pill("配置版本指纹", hashShort, false),
    pill("股票池范围", snap.universe != null ? String(snap.universe) : "—", false),
    pill("引擎侧市场提示", snap.regime_hint != null ? String(snap.regime_hint) : "—", false),
    pill("观察池已合并", snap.watchlist_merged ? "是" : "否", !snap.watchlist_merged),
    pill("审计文件格式", snap.schema_ok === true ? "校验通过" : snap.schema_ok === false ? "异常" : "—", snap.schema_ok === false),
    pill("审计写入时间", snap.artifact_written_at || "—", false),
  ];
  const issues =
    snap.schema_issues && snap.schema_issues.length
      ? `<div class="screening-snap-issues small">格式校验提示：${esc(JSON.stringify(snap.schema_issues))}</div>`
      : "";
  el.innerHTML = `<div class="screening-snap-grid">${rows.join("")}</div>${issues}`;
}

function renderLeft(data) {
  const el = qs("screeningLeft");
  if (!el) return;
  const wc = data.weekly_calibration || {};
  const ep = data.emergency_pause || {};
  const eff = data.effective_pause || {};
  const pol = data.screening_policy || {};
  const sent = data.sentiment_snapshot || {};
  const sentKeys = Object.keys(sent).filter((k) => k !== "note");
  const sentBody = sentKeys.length > 0 ? sentimentRowsHtml(sent) : emptySentimentHelp();
  const noteExtra = sent.note ? `<div class="small" style="margin-top:8px;opacity:0.9;">${esc(String(sent.note))}</div>` : "";

  const rawRegime = wc.regime;
  const regimeLabel = regimeDisplayLabel(rawRegime);
  const narrative = regimeNarrativeFor(rawRegime);
  const updatedLine = formatCalibrationUpdated(wc);
  const notesBlock = calibrationNotesForHumans(wc);

  const epActive = !!ep.active;
  const epReason = esc(ep.reason || "");
  const epUntil = esc(ep.until || "");

  const pauseClass = eff.blocked ? "screening-card pause-border" : "screening-card ok-border";
  el.innerHTML = `
    <div class="screening-h4">市场状态与策略定调</div>
    <div class="screening-card">
      <div class="screening-badge-regime">${esc(regimeLabel)}</div>
      <p class="small" style="margin:0 0 8px 0;line-height:1.45;">${esc(narrative)}</p>
      <p class="small screening-muted" style="margin:0;">${updatedLine}</p>
      ${notesBlock}
    </div>
    <div class="screening-h4" style="margin-top:12px;">市场情绪与资金面（摘要）</div>
    <div class="screening-card small">
      ${sentBody}
      ${noteExtra}
    </div>
    <div class="screening-h4" style="margin-top:12px;">风控门闸（能否写入观察池）</div>
    <div class="${pauseClass}">
      <div><strong>当前是否拦截写入</strong>：${eff.blocked ? "是 — 观察池不会更新" : "否 — 允许按审计结果合并观察池"}</div>
      <div class="small" style="margin-top:4px;">${eff.blocked ? esc(eff.reason || "—") : "未触发门闸；若定调或熔断要求暂停，此处会显示原因。"}</div>
      <div class="small" style="margin-top:6px;">周度定调暂停：${eff.weekly_regime_pause ? "是" : "否"} · 紧急熔断：${
        eff.emergency_pause_active ? "已触发" : "未触发"
      }</div>
    </div>
    <div class="screening-h4" style="margin-top:12px;">紧急熔断状态</div>
    <div class="screening-card">
      <div><strong>熔断是否生效</strong>：${epActive ? "是 — 夜盘可能跳过或收紧写入" : "否 — 未处于熔断"}</div>
      ${epReason ? `<div class="small" style="margin-top:6px;">原因：${epReason}</div>` : ""}
      ${epUntil ? `<div class="small">预计解除：${epUntil}</div>` : ""}
    </div>
    <div class="screening-h4" style="margin-top:12px;">数据质量门槛</div>
    <div class="screening-card small">
      <div style="line-height:1.45;">${qualityPolicyHuman(pol)}</div>
    </div>
  `;
}

function renderWatchlist(wl) {
  const el = qs("screeningWatchlist");
  if (!el) return;
  const syms = (wl && wl.symbols) || [];
  const meta = (wl && wl.meta) || {};
  const ls = meta.last_screening || {};
  const hasLs = ls && typeof ls === "object" && Object.keys(ls).length > 0;
  const rows = cachedSummary?.latest_screening_rows || [];
  const scoreMap = new Map();
  for (const r of rows) {
    if (r && typeof r === "object" && r.symbol && r.score != null) scoreMap.set(String(r.symbol), r.score);
  }
  const wlPairs = syms.slice(0, 20).map((s) => {
    const sc = scoreMap.has(String(s)) ? `(${scoreMap.get(String(s))})` : "";
    return `${esc(String(s))}${sc ? `<span class="screening-muted"> ${esc(sc)}</span>` : ""}`;
  });
  const lastSummaryCard = (() => {
    if (!hasLs) return "";
    const quality = ls.quality_score != null ? ls.quality_score : "—";
    const degraded =
      ls.degraded === true ? "是（需谨慎）" : ls.degraded === false ? "否" : "—";
    const cfg = ls.config_hash ? String(ls.config_hash) : "—";
    const cfgShort = cfg.length > 14 ? `${cfg.slice(0, 10)}…` : cfg;
    const pluginVer = ls.plugin_version != null ? ls.plugin_version : "—";
    const universe = ls.universe != null ? ls.universe : "—";
    return `
      <div class="screening-h4" style="margin-top:10px;">上次合并摘要</div>
      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">质量分</div><div class="kpi-value">${esc(String(quality))}</div></div>
        <div class="kpi-card"><div class="kpi-label">是否降级</div><div class="kpi-value">${esc(String(degraded))}</div></div>
        <div class="kpi-card"><div class="kpi-label">配置指纹</div><div class="kpi-value">${esc(String(cfgShort))}</div></div>
        <div class="kpi-card"><div class="kpi-label">插件版本 / 标的池</div><div class="kpi-value">${esc(
          String(pluginVer),
        )} · ${esc(String(universe))}</div></div>
      </div>
      <details class="screening-details" style="margin-top:6px;">
        <summary>查看原始 last_screening JSON</summary>
        <pre class="small screening-pre" style="margin-top:6px;">${esc(JSON.stringify(ls, null, 2))}</pre>
      </details>
    `;
  })();
  el.innerHTML = `
    <div><strong>当前观察池标的</strong>：${
      syms.length ? wlPairs.join("，") : "（尚无 — 可能尚未合并夜盘结果或名单为空）"
    }</div>
    <div class="small screening-muted" style="margin-top:6px;">对应仓库内观察池清单文件；与中间表格「候选证券」可能不同步，以右侧当日审计为准。</div>
    ${lastSummaryCard}
  `;
}

function renderTable(rows) {
  const thead = qs("screeningThead");
  const tbody = qs("screeningTbody");
  const facPre = qs("screeningFactorDetail");
  if (!thead || !tbody) return;
  if (facPre) {
    facPre.style.display = "none";
    facPre.textContent = "";
  }
  tbody.innerHTML = "";
  thead.innerHTML = "";
  const list = Array.isArray(rows) ? rows.filter((x) => x && typeof x === "object") : [];
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="4">暂无候选证券行（请选日期或确认夜盘审计已产出）。</td>`;
    tbody.appendChild(tr);
    return;
  }
  const cols = inferColumns(list);
  const hasRowFactors = list.some((r) => r && (r.factors != null || r.raw_factors != null));
  const scoreTone = (v) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return "";
    if (n >= 75) return "tone-high";
    if (n >= 65) return "tone-mid";
    if (n >= 55) return "tone-low";
    return "tone-bad";
  };
  const trh = document.createElement("tr");
  for (const c of cols) {
    const th = document.createElement("th");
    th.textContent = TABLE_COL_LABEL[c] || c;
    trh.appendChild(th);
  }
  if (hasRowFactors) {
    const th = document.createElement("th");
    th.textContent = "因子明细";
    trh.appendChild(th);
  }
  thead.appendChild(trh);

  for (const r of list) {
    const tr = document.createElement("tr");
    for (const c of cols) {
      const td = document.createElement("td");
      const v = r[c];
      if (c === "symbol" && v) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "screening-sym-btn";
        btn.textContent = String(v);
        btn.title = "在「图形」页打开该代码 K 线（便于与选股日对照）";
        btn.addEventListener("click", () => {
          const d = qs("screeningDatePick")?.value || "";
          const p = d ? { screeningDate: d } : {};
          loadChartForSymbol(String(v).trim(), p).catch((e) => console.error(e));
        });
        td.appendChild(btn);
      } else if ((c === "score" || c === "quality_score") && v != null) {
        const span = document.createElement("span");
        span.className = `screening-score-chip ${scoreTone(v)}`.trim();
        span.textContent = typeof v === "number" ? v.toFixed(1) : String(v);
        td.appendChild(span);
      } else {
        td.textContent = typeof v === "object" ? JSON.stringify(v).slice(0, 200) : formatCell(v);
      }
      tr.appendChild(td);
    }
    if (hasRowFactors) {
      const td = document.createElement("td");
      const raw = r.factors != null ? r.factors : r.raw_factors;
      if (raw != null) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "screening-sym-btn";
        b.textContent = "查看";
        b.title = "查看该行因子拆解（归因）";
        b.addEventListener("click", () => {
          if (!facPre) return;
          facPre.style.display = "block";
          try {
            facPre.textContent = JSON.stringify(raw, null, 2);
          } catch (e) {
            facPre.textContent = String(raw);
          }
        });
        td.appendChild(b);
      } else {
        td.textContent = "—";
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function renderBanner(data) {
  const b = qs("screeningBanner");
  if (!b) return;
  const eff = data.effective_pause || {};
  if (eff.blocked) {
    b.style.display = "block";
    b.className = "screening-banner pause";
    b.textContent = `门闸提示：当前不允许更新观察池。原因：${eff.reason || "见左侧说明"}`;
  } else {
    b.style.display = "block";
    b.className = "screening-banner ok";
    b.textContent = "门闸提示：当前允许按夜盘审计合并观察池（具体名单以表格与右侧审计为准）。";
  }
}

function renderAuditFromArtifact(art) {
  const el = qs("screeningAudit");
  if (!el) return;
  if (!art) {
    el.textContent = "暂无该日审计记录。";
    return;
  }
  const fmtArr = (x) => {
    if (!Array.isArray(x) || x.length === 0) return "—";
    return JSON.stringify(x);
  };
  const lines = [
    `审计基准日（选股日）：${art.run_date || "—"}`,
    `文件写入时间：${art.written_at || "—"}`,
    `审计文件格式：${art.schema_ok === true ? "通过" : art.schema_ok === false ? "异常" : "—"}`,
    `格式说明：${JSON.stringify(art.schema_issues || [])}`,
    `熔断是否生效：${art.pause_active ? "是" : "否"}`,
    `熔断原因：${art.pause_reason || "—"}`,
    `是否允许写入观察池：${art.watchlist_allowed ? "是" : "否"}`,
    `观察池合并路径：${art.merged_watchlist_path || "—"}`,
    `跳过写入说明：${fmtArr(art.watchlist_skipped)}`,
    `门闸原因列表：${fmtArr(art.gate_reasons)}`,
  ];
  el.textContent = lines.join("\n");
}

function renderMetricsFromCache() {
  const el = qs("screeningAggregate");
  const srcEl = qs("screeningMetricsSource");
  if (!el) return;
  const mode = srcEl?.value || "screening";
  if (!cachedSummary) {
    el.textContent = "";
    return;
  }

  const kpi = (label, value, hint) => {
    const v = value == null || value === "" ? "—" : String(value);
    const h = hint ? `<div class="kpi-hint">${esc(hint)}</div>` : "";
    return `<div class="kpi-card"><div class="kpi-label">${esc(label)}</div><div class="kpi-value">${esc(v)}</div>${h}</div>`;
  };
  const details = (title, obj) =>
    `<details class="screening-details"><summary>${esc(title)}</summary><pre class="small screening-pre" style="margin-top:6px;">${esc(
      JSON.stringify(obj || {}, null, 2),
    )}</pre></details>`;

  if (mode === "weekly_review") {
    const wr = cachedSummary.weekly_review;
    if (!wr) {
      el.innerHTML =
        `<div class="small screening-muted">尚未找到周度复盘数据文件。</div>` +
        `<div class="small screening-muted" style="margin-top:6px;">若已启用周度复盘落盘，请将模板写入 <code>data/screening/weekly_review.json</code> 后刷新。</div>`;
      return;
    }
    const m = wr.metrics || {};
    const period = wr.period_label || wr.as_of || "—";
    const hit = m.hit_rate_5d_pct == null ? "—" : `${Number(m.hit_rate_5d_pct) * 100}%`;
    const avgMax = m.avg_max_return_5d_pct == null ? "—" : `${Number(m.avg_max_return_5d_pct) * 100}%`;
    el.innerHTML = `
      <div class="kpi-grid">
        ${kpi("复盘区间", period, "来自 weekly_review.json")}
        ${kpi("5日命中率", hit, "未落盘时为 —")}
        ${kpi("5日平均最大收益", avgMax, "未落盘时为 —")}
        ${kpi("暂停事件数", m.pause_events_count ?? "—", "")}
      </div>
      ${details("查看原始周复盘 JSON", wr)}
    `;
    return;
  }

  const agg = cachedSummary.aggregate || {};
  el.innerHTML = `
    <div class="kpi-grid">
      ${kpi("窗口天数", agg.window_dates ?? "—", "最近 N 次夜盘审计")}
      ${kpi("已合并观察池次数", agg.runs_with_watchlist_merged ?? "—", "")}
      ${kpi("暂停运行次数", agg.runs_with_pause_active ?? "—", "")}
      ${kpi("质量分样本数", (agg.quality_score_series || []).length || "—", "quality_score_series")}
    </div>
    ${details("查看原始夜盘聚合 JSON", agg)}
  `;
}

async function loadDateArtifact(dateStr) {
  const status = qs("screeningStatus");
  try {
    const r = await jgetWithFallback(
      `/api/semantic/screening_view?trade_date=${encodeURIComponent(dateStr)}`,
      `/api/screening/by-date?date=${encodeURIComponent(dateStr)}`,
    );
    if (!r.success) {
      if (status) status.textContent = r.message || "加载失败";
      renderAuditFromArtifact(null);
      renderTable([]);
      renderRunSnapshot(null);
      return;
    }
    const art = r.data || {};
    const nightlyRows = (((art.candidates || {}).nightly) || []);
    renderAuditFromArtifact(null);
    renderTable(Array.isArray(nightlyRows) ? nightlyRows : []);
    renderRunSnapshot(null);
    if (status) status.textContent = `已选审计日: ${dateStr}`;
  } catch (e) {
    if (status) status.textContent = String(e?.message || e);
  }
}

async function loadScreening() {
  const status = qs("screeningStatus");
  if (status) status.textContent = "加载中…";
  try {
    const r = await jgetWithFallback("/api/semantic/dashboard", "/api/screening/summary");
    if (!r.success || !r.data) {
      if (status) status.textContent = r.message || "加载页面摘要失败";
      return;
    }
    const data = {
      weekly_calibration: (r.data || {}).market_state || {},
      emergency_pause: ((r.data || {}).risk_snapshot || {}).emergency_pause || {},
      effective_pause: {
        blocked: !!((r.data || {}).market_state || {}).pause_status,
        reason: ((r.data || {}).risk_snapshot || {}).latest_gate_reason || null,
      },
      screening_policy: {},
      watchlist: { symbols: [] },
      latest_screening_date: ((r.data || {})._meta || {}).trade_date || null,
      latest_artifact: null,
      latest_screening: null,
      latest_screening_rows: [],
      aggregate: {},
      sentiment_snapshot: (r.data || {}).sentiment_temperature || {},
      weekly_review: null,
      run_snapshot: {},
    };
    cachedSummary = data;
    renderPhaseHint();
    renderBanner(data);
    renderLeft(data);
    renderWatchlist(data.watchlist || {});
    renderMetricsFromCache();

    const hist = await jgetWithFallback("/api/semantic/trade_dates", "/api/tail_screening/history");
    const dates = Array.isArray(hist.data)
      ? hist.data.map((x) => (typeof x === "string" ? x : x.date)).filter(Boolean)
      : [];
    lastDates = dates;
    const pick = qs("screeningDatePick");
    if (pick) {
      pick.innerHTML = dates
        .slice()
        .reverse()
        .map((d) => `<option value="${esc(d)}">${esc(d)}</option>`)
        .join("");
      const def = data.latest_screening_date || dates[dates.length - 1] || "";
      if (def && Array.from(pick.options).some((o) => o.value === def)) {
        pick.value = def;
      } else if (pick.options.length) {
        pick.selectedIndex = 0;
      }
    }

    const selected = pick?.value || data.latest_screening_date;
    if (selected) {
      await loadDateArtifact(selected);
    } else {
      renderTable([]);
      renderAuditFromArtifact(null);
      renderRunSnapshot(null);
      if (status) status.textContent = "暂无历史审计文件，请先完成夜盘落盘。";
    }
  } catch (e) {
    if (status) status.textContent = String(e?.message || e);
  }
}

const TAIL_PARADIGM_TBODY = {
  fund_flow_follow: "tailPoolFundFlowTbody",
  tail_grab: "tailPoolTailGrabTbody",
  oversold_bounce: "tailPoolOversoldTbody",
  sector_rotation: "tailPoolSectorRotTbody",
};

function _tailRecommendedToTbody(tbodyId, rows) {
  const tbody = qs(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = "";
  const list = Array.isArray(rows) ? rows : [];
  const colspan = 12;
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="${colspan}">暂无数据</td>`;
    tbody.appendChild(tr);
    return;
  }
  for (const r of list) {
    const tr = document.createElement("tr");
    const reasons = Array.isArray(r?.reasons) ? r.reasons.join("；") : "";
    const tags = Array.isArray(r?.source_tags) ? r.source_tags.join(", ") : "";
    const comp = r.composite_score != null ? Number(r.composite_score).toFixed(2) : "";
    const ord = r.display_order != null ? r.display_order : "";
    const nb = r.northbound_align != null ? r.northbound_align : "";
    tr.innerHTML = `<td>${esc(ord)}</td><td>${esc(r.symbol || "")}</td><td>${esc(r.name || "")}</td><td>${esc(
      r.sector_name || "",
    )}</td><td>${esc(comp)}</td><td>${esc(r.score != null ? r.score : "")}</td><td>${esc(tags)}</td><td>${esc(
      nb,
    )}</td><td>${esc(r.pct_change == null ? "" : `${Number(r.pct_change).toFixed(2)}%`)}</td><td>${esc(
      r.volume_ratio == null ? "" : Number(r.volume_ratio).toFixed(2),
    )}</td><td>${esc(r.stop_loss || "-3%")}</td><td>${esc(reasons)}</td>`;
    tbody.appendChild(tr);
  }
}

function _tailParadigmPoolToTbody(tbodyId, rows) {
  const tbody = qs(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = "";
  const list = Array.isArray(rows) ? rows : [];
  const colspan = 7;
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="${colspan}">暂无数据（上游失败或未过入池线）</td>`;
    tbody.appendChild(tr);
    return;
  }
  for (const r of list) {
    const tr = document.createElement("tr");
    const reasons = Array.isArray(r?.reasons) ? r.reasons.join("；") : "";
    const ps = r.paradigm_score != null ? r.paradigm_score : "";
    tr.innerHTML = `<td>${esc(r.symbol || "")}</td><td>${esc(r.name || "")}</td><td>${esc(
      r.sector_name || "",
    )}</td><td>${esc(ps)}</td><td>${esc(
      r.pct_change == null ? "" : `${Number(r.pct_change).toFixed(2)}%`,
    )}</td><td>${esc(r.volume_ratio == null ? "" : Number(r.volume_ratio).toFixed(2))}</td><td>${esc(reasons)}</td>`;
    tbody.appendChild(tr);
  }
}

function renderTailParadigmPools(art) {
  const pools = art?.paradigm_pools || {};
  for (const [pid, tbodyId] of Object.entries(TAIL_PARADIGM_TBODY)) {
    _tailParadigmPoolToTbody(tbodyId, pools[pid] || []);
  }
}

function renderTailSummary(data) {
  const el = qs("tailScreeningSummary");
  if (!el) return;
  const latest = data?.latest || {};
  const summary = latest?.summary || {};
  const trace = latest?.tool_trace || {};
  if (!latest || Object.keys(latest).length === 0) {
    el.innerHTML = '<div class="screening-muted">暂无尾盘结果，请先执行尾盘任务。</div>';
    return;
  }
  const noReason = summary.no_candidate_reason ? `<div class="small" style="margin-top:6px;color:#f7c88a;"><strong>空结果说明</strong>：${esc(summary.no_candidate_reason)}</div>` : "";
  const sourceLine = trace.candidate_source ? `<div><strong>候选来源</strong>：${esc(trace.candidate_source)}</div>` : "";
  const dqLine = summary.data_quality ? `<div><strong>数据质量</strong>：${esc(summary.data_quality)}</div>` : "";
  const prof = summary.applied_profile || latest.applied_profile || "—";
  const sv = latest.scoring_version || "—";
  const cov = summary.sector_name_coverage || {};
  const covLine =
    cov.recommended_pct != null || cov.paradigm_pools_pct != null
      ? `<div><strong>板块名覆盖率</strong>：推荐 ${esc(cov.recommended_pct ?? "—")}% / 候选池 ${esc(cov.paradigm_pools_pct ?? "—")}%</div>`
      : "";
  const pools = latest.paradigm_pools || {};
  const poolCounts = Object.entries(TAIL_PARADIGM_TBODY)
    .map(([pid]) => `${pid}: ${(pools[pid] || []).length}`)
    .join("；");
  const mr = latest.market_regime || "—";
  const rnotes = Array.isArray(latest.regime_detection_notes) ? latest.regime_detection_notes : [];
  const rnotesLine =
    rnotes.length > 0
      ? `<div class="small" style="margin-top:4px;"><strong>制度检测备注</strong>：${esc(rnotes.join("；"))}</div>`
      : "";
  el.innerHTML = `
    <div><strong>运行日期</strong>：${esc(latest.run_date || "—")}</div>
    <div><strong>运行ID</strong>：${esc(latest.run_id || "—")}</div>
    <div><strong>生成时间</strong>：${esc(latest.generated_at || "—")}</div>
    <div><strong>阶段</strong>：${esc(latest.stage || "—")}</div>
    <div><strong>market_regime</strong>：${esc(mr)}</div>
    <div><strong>参数族 applied_profile</strong>：${esc(prof)}</div>
    <div><strong>scoring_version</strong>：${esc(sv)}</div>
    <div><strong>推荐池条数</strong>：${esc(summary.recommended_count || 0)}（综合前5: ${esc(summary.composite_top5_count ?? "—")}；仅池第一补入: ${esc(summary.pool_first_only_count ?? "—")}）</div>
    <div><strong>范式池非空数</strong>：${esc(summary.pools_nonempty_count ?? "—")}</div>
    <div><strong>候选池合计条数</strong>：${esc(summary.passed_hard_conditions || 0)}</div>
    <div class="small" style="margin-top:4px;word-break:break-all;"><strong>各池条数</strong>：${esc(poolCounts)}</div>
    ${covLine}
    ${dqLine}
    ${sourceLine}
    ${rnotesLine}
    ${noReason}
  `;
}

function renderTailAudit(art) {
  const el = qs("tailScreeningAudit");
  if (!el) return;
  if (!art) {
    el.textContent = "暂无该日记录。";
    return;
  }
  el.textContent = JSON.stringify(
    {
      run_id: art.run_id,
      run_date: art.run_date,
      generated_at: art.generated_at,
      stage: art.stage,
      applied_profile: art.applied_profile,
      market_regime: art.market_regime,
      regime_detection_notes: art.regime_detection_notes,
      scoring_version: art.scoring_version,
      gate_snapshot: art.gate_snapshot || {},
      summary: art.summary || {},
      paradigm_pools: art.paradigm_pools || {},
      recommended: art.recommended || [],
      tool_trace: art.tool_trace || {},
      skip_reason: art.skip_reason || null,
    },
    null,
    2,
  );
}

async function loadTailByDate(dateStr) {
  const status = qs("tailScreeningStatus");
  try {
    const r = await jgetWithFallback(
      `/api/semantic/screening_view?trade_date=${encodeURIComponent(dateStr)}`,
      `/api/tail_screening/by-date?date=${encodeURIComponent(dateStr)}`,
    );
    if (!r.success) {
      if (status) status.textContent = r.message || "加载失败";
      _tailRecommendedToTbody("tailRecommendedTbody", []);
      renderTailParadigmPools({});
      renderTailAudit(null);
      return;
    }
    const art = r.data || {};
    const tailRows = (((art.candidates || {}).tail) || []);
    const pools = art.tail_paradigm_pools && typeof art.tail_paradigm_pools === "object" ? art.tail_paradigm_pools : {};
    const head = art.tail_source && typeof art.tail_source === "object" ? art.tail_source : {};
    _tailRecommendedToTbody("tailRecommendedTbody", tailRows);
    renderTailParadigmPools({ paradigm_pools: pools });
    renderTailAudit({ ...head, recommended: tailRows, paradigm_pools: pools });
    tailCached = { latest: { ...head, recommended: tailRows, paradigm_pools: pools }, latest_date: dateStr };
    renderTailSummary(tailCached);
    if (status) status.textContent = `已选日期: ${dateStr}`;
  } catch (e) {
    if (status) status.textContent = String(e?.message || e);
  }
}

async function loadTailScreening() {
  const status = qs("tailScreeningStatus");
  if (status) status.textContent = "加载中…";
  try {
    const summary = await jgetWithFallback("/api/semantic/dashboard", "/api/tail_screening/summary");
    if (!summary.success) {
      if (status) status.textContent = summary.message || "加载失败";
      return;
    }
    tailCached = { latest: { recommended: (summary.data || {}).top_recommendations || [] }, latest_date: ((summary.data || {})._meta || {}).trade_date };
    const hist = await jgetWithFallback("/api/semantic/trade_dates", "/api/tail_screening/history");
    const dates = Array.isArray(hist.data)
      ? hist.data.map((x) => (typeof x === "string" ? x : x.date)).filter(Boolean)
      : [];
    const pick = qs("tailScreeningDatePick");
    if (pick) {
      pick.innerHTML = dates
        .slice()
        .reverse()
        .map((d) => `<option value="${esc(d)}">${esc(d)}</option>`)
        .join("");
      const def = tailCached.latest_date || dates[dates.length - 1] || "";
      if (def && Array.from(pick.options).some((o) => o.value === def)) {
        pick.value = def;
      } else if (pick.options.length) {
        pick.selectedIndex = 0;
      }
    }
    const selected = pick?.value || tailCached.latest_date;
    if (selected) {
      await loadTailByDate(selected);
    } else {
      const latest = tailCached.latest || {};
      _tailRecommendedToTbody("tailRecommendedTbody", latest.recommended || []);
      renderTailParadigmPools(latest);
      renderTailAudit(latest);
      renderTailSummary(tailCached);
      if (status) status.textContent = "暂无历史文件，仅显示 latest。";
    }
  } catch (e) {
    if (status) status.textContent = String(e?.message || e);
  }
}

function renderResearchTop(rows) {
  const tbody = qs("researchTopTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td colspan='4'>暂无推荐</td>";
    tbody.appendChild(tr);
    return;
  }
  for (const r of list) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(r.symbol || "")}</td><td>${esc(r.name || "")}</td><td>${esc(r.score ?? r.composite_score ?? "")}</td><td>${esc((r.source_tags || []).join(","))}</td>`;
    tbody.appendChild(tr);
  }
}

function renderResearchKV(elId, rows) {
  const el = qs(elId);
  if (!el) return;
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) {
    el.innerHTML = `<div class="small screening-muted">暂无数据</div>`;
    return;
  }
  el.innerHTML = list
    .map(
      (x) =>
        `<div class="research-kv"><div class="research-k">${esc(x.k)}</div><div class="research-v">${esc(
          x.v == null || x.v === "" ? "—" : String(x.v),
        )}</div></div>`,
    )
    .join("");
}

function fmtNum(v, digits = 2) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function fmtPctNumber(v, digits = 2) {
  const n = Number(v);
  return Number.isFinite(n) ? `${n.toFixed(digits)}%` : "—";
}

function renderSixIndexSummaryCards(payload) {
  const el = qs("researchSixIndexSummaryCards");
  if (!el) return;
  const summary = payload && typeof payload.summary === "object" ? payload.summary : {};
  const meta = payload && typeof payload._meta === "object" ? payload._meta : {};
  const verify = payload && typeof payload.verification_summary === "object" ? payload.verification_summary : {};
  const weekly = payload && typeof payload.weekly_metrics_summary === "object" ? payload.weekly_metrics_summary : {};
  const verifyAcc =
    verify.available && Number.isFinite(Number(verify.accuracy)) ? `${(Number(verify.accuracy) * 100).toFixed(1)}%` : "—";
  const weeklyHit =
    weekly.available && Number.isFinite(Number(weekly.hit_rate)) ? `${(Number(weekly.hit_rate) * 100).toFixed(1)}%` : "—";
  const weeklyBrier = weekly.available && Number.isFinite(Number(weekly.brier_score)) ? Number(weekly.brier_score).toFixed(4) : "—";
  const cards = [
    { label: "看多", value: summary.up_count ?? 0, hint: "direction=up" },
    { label: "看空", value: summary.down_count ?? 0, hint: "direction=down" },
    { label: "中性", value: summary.neutral_count ?? 0, hint: "direction=neutral" },
    { label: "质量", value: meta.quality_status || "unknown", hint: meta.generated_at || "—" },
    { label: "最新验证命中", value: verifyAcc, hint: verify.target_date || "无已验证样本" },
    { label: "20日命中率", value: weeklyHit, hint: `n=${weekly.samples ?? 0}` },
    { label: "20日Brier", value: weeklyBrier, hint: weekly.as_of_target_date || "—" },
  ];
  el.innerHTML = cards
    .map(
      (c) => `<div class="kpi-card">
        <div class="kpi-label">${esc(c.label)}</div>
        <div class="kpi-value">${esc(c.value)}</div>
        <div class="kpi-hint">${esc(c.hint)}</div>
      </div>`,
    )
    .join("");
}

function renderSixIndexMeta(payload) {
  const meta = payload && typeof payload._meta === "object" ? payload._meta : {};
  const verify = payload && typeof payload.verification_summary === "object" ? payload.verification_summary : {};
  const weekly = payload && typeof payload.weekly_metrics_summary === "object" ? payload.weekly_metrics_summary : {};
  researchSixIndexSnapshot = payload && typeof payload === "object" ? payload : {};
  const generatedAt = String(meta.generated_at || "");
  const generatedAtDisplay = generatedAt ? generatedAt.replace("T", " ").replace("+08:00", " +08:00") : "—";
  renderResearchKV("researchSixIndexMeta", [
    { k: "交易日", v: payload?.trade_date || "—" },
    { k: "预测目标日", v: payload?.predict_for_trade_date || "—" },
    { k: "整体质量", v: meta.quality_status || "unknown" },
    { k: "生成时间", v: generatedAtDisplay },
    { k: "最近已验证目标日", v: verify.available ? verify.target_date || "—" : "无" },
    { k: "最近已验证样本数", v: verify.available ? verify.verified_count ?? 0 : 0 },
    { k: "20日样本覆盖", v: weekly.available ? fmtPctNumber(Number(weekly.coverage || 0) * 100, 1) : "—" },
  ]);
  const statusEl = qs("researchSixIndexStatus");
  if (statusEl) {
    const reasons = (Array.isArray(payload?.predictions) ? payload.predictions : [])
      .flatMap((row) => {
        const raw = String(row?.degraded_reason || "").trim();
        if (!raw) return [];
        return raw
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean)
          .map((item) => ({ indexName: row?.index_name || row?.index_code || "—", reason: item }));
      });
    if (!reasons.length) {
      statusEl.textContent = "当前快照质量正常。";
    } else {
      statusEl.innerHTML = `<div class="research-six-index-status-title">当前存在质量提示项</div><ul class="research-six-index-status-list">${reasons
        .map((item) => `<li><strong>${esc(item.indexName)}</strong>: ${esc(item.reason)}</li>`)
        .join("")}</ul>`;
    }
  }
}

function buildSixIndexClipboardText(payload) {
  const p = payload && typeof payload === "object" ? payload : {};
  const predictions = Array.isArray(p.predictions) ? p.predictions.slice() : [];
  const ordered = predictions.sort((a, b) => {
    const ai = SIX_INDEX_ORDER.indexOf(String(a?.index_code || ""));
    const bi = SIX_INDEX_ORDER.indexOf(String(b?.index_code || ""));
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
  const lines = [
    "六指数次日预测",
    `交易日: ${p.trade_date || "—"}`,
    `预测目标日: ${p.predict_for_trade_date || "—"}`,
    `方向统计: up=${p?.summary?.up_count ?? 0}, down=${p?.summary?.down_count ?? 0}, neutral=${p?.summary?.neutral_count ?? 0}`,
    `最新验证: ${
      p?.verification_summary?.available
        ? `${p.verification_summary.target_date} 命中率 ${fmtPctNumber(Number(p.verification_summary.accuracy || 0) * 100, 1)}`
        : "暂无"
    }`,
    `20日指标: ${
      p?.weekly_metrics_summary?.available
        ? `hit=${fmtPctNumber(Number(p.weekly_metrics_summary.hit_rate || 0) * 100, 1)}, brier=${fmtNum(
            p.weekly_metrics_summary.brier_score,
            4,
          )}, n=${p.weekly_metrics_summary.samples ?? 0}`
        : "暂无"
    }`,
    "",
  ];
  for (const row of ordered) {
    lines.push(
      `${row?.index_name || "—"}(${row?.index_code || "—"}): ${row?.direction || "—"} / 概率 ${fmtPctNumber(row?.probability)} / 置信度 ${
        row?.confidence || "—"
      } / 质量 ${row?.quality_status || "unknown"}`,
    );
  }
  return lines.join("\n");
}

function renderSixIndexCards(payload) {
  const wrap = qs("researchSixIndexCards");
  const empty = qs("researchSixIndexEmpty");
  if (!wrap) return;
  const predictions = Array.isArray(payload?.predictions) ? payload.predictions.slice() : [];
  const ordered = predictions.sort((a, b) => {
    const ai = SIX_INDEX_ORDER.indexOf(String(a?.index_code || ""));
    const bi = SIX_INDEX_ORDER.indexOf(String(b?.index_code || ""));
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
  if (empty) empty.style.display = ordered.length ? "none" : "block";
  if (!ordered.length) {
    wrap.innerHTML = "";
    return;
  }
  wrap.innerHTML = ordered
    .map((row) => {
      const direction = String(row?.direction || "neutral");
      const quality = String(row?.quality_status || "unknown");
      const signalItems = Object.entries(row?.signals || {});
      const score = row?.score_breakdown?.total_score;
      return `<section class="research-six-index-card">
        <div class="research-six-index-head">
          <div>
            <div class="research-six-index-title">${esc(row?.index_name || "—")}</div>
            <div class="small screening-muted">${esc(row?.index_code || "—")}</div>
          </div>
          <div class="research-six-index-badges">
            <span class="research-dir-badge tone-${esc(direction)}">${esc(direction)}</span>
            <span class="research-quality-badge tone-${esc(quality)}">${esc(quality)}</span>
          </div>
        </div>
        <div class="research-six-index-stats">
          <div class="research-kv"><div class="research-k">概率</div><div class="research-v research-v-mono research-v-probability">${esc(fmtPctNumber(row?.probability))}</div></div>
          <div class="research-kv"><div class="research-k">置信度</div><div class="research-v">${esc(row?.confidence || "—")}</div></div>
          <div class="research-kv research-six-index-score"><div class="research-k">总分</div><div class="research-v research-v-mono">${esc(fmtNum(score, 4))}</div></div>
        </div>
        <div class="small">${esc(row?.reasoning || "—")}</div>
        <details class="screening-details">
          <summary>查看因子与降级细节</summary>
          <div class="research-six-index-detail">
            <div class="research-kv"><div class="research-k">降级原因</div><div class="research-v">${esc(row?.degraded_reason || "无")}</div></div>
            <div class="research-kv"><div class="research-k">模型</div><div class="research-v">${esc(row?.model_family || "—")}</div></div>
            <div class="research-kv"><div class="research-k">signals</div><div class="research-v"><pre class="research-json-pre">${esc(JSON.stringify(row?.signals || {}, null, 2))}</pre></div></div>
            <div class="research-kv"><div class="research-k">score_breakdown</div><div class="research-v"><pre class="research-json-pre">${esc(
              JSON.stringify(row?.score_breakdown || {}, null, 2),
            )}</pre></div></div>
            ${
              signalItems.length
                ? `<div class="research-six-index-pill-row">${signalItems
                    .map(([k, v]) => `<span class="screening-factor-pill">${esc(k)}=${esc(typeof v === "number" ? fmtNum(v, 4) : v)}</span>`)
                    .join("")}</div>`
                : ""
            }
          </div>
        </details>
      </section>`;
    })
    .join("");
}

function renderResearchTimeline(events) {
  const el = qs("researchTimeline");
  if (!el) return;
  const onlyAnomaly = !!qs("researchTimelineOnlyAnomaly")?.checked;
  const src = Array.isArray(events) ? events : [];
  const list = onlyAnomaly ? src.filter((e) => String(e?.quality_status || "") === "degraded") : src;
  if (!list.length) {
    el.innerHTML = `<div class="small screening-muted">暂无时间轴事件</div>`;
    return;
  }
  el.innerHTML = list
    .map((e) => {
      const quality = e.quality_status === "degraded" ? "数据降级" : "正常";
      const tone = e.quality_status === "degraded" ? "tone-warn" : "";
      return `<div class="research-timeline-item ${tone}">
        <div class="research-timeline-meta">${esc(e.event_time || "—")} · ${esc(e.task_id || "unknown")} · ${esc(quality)}</div>
        <div>${esc(e.summary || "—")}</div>
      </div>`;
    })
    .join("");
}

function renderSubTimeline(targetId, events, onlyAnomaly) {
  const el = qs(targetId);
  if (!el) return;
  const src = Array.isArray(events) ? events : [];
  const list = onlyAnomaly ? src.filter((e) => String(e?.quality_status || "") === "degraded") : src;
  if (!list.length) {
    el.innerHTML = `<div class="small screening-muted">暂无时间轴事件</div>`;
    return;
  }
  el.innerHTML = list
    .map((e) => {
      const quality = e.quality_status === "degraded" ? "数据降级" : "正常";
      const tone = e.quality_status === "degraded" ? "tone-warn" : "";
      return `<div class="research-timeline-item ${tone}">
        <div class="research-timeline-meta">${esc(e.event_time || "—")} · ${esc(e.task_id || "unknown")} · ${esc(quality)}</div>
        <div>${esc(e.summary || "—")}</div>
      </div>`;
    })
    .join("");
}

async function loadTimelineInto(targetDate, targetId, onlyAnomaly = false) {
  if (!targetDate) {
    renderSubTimeline(targetId, [], onlyAnomaly);
    return;
  }
  const timeline = await jgetWithFallback(`/api/semantic/timeline?trade_date=${encodeURIComponent(targetDate)}`, "");
  const events = (timeline.data || {}).events || [];
  renderSubTimeline(targetId, events, onlyAnomaly);
}

function renderResearchQuality(meta) {
  const el = qs("researchQualityBadge");
  if (!el) return;
  const m = meta && typeof meta === "object" ? meta : {};
  const q = String(m.quality_status || "unknown");
  const refs = Array.isArray(m.lineage_refs) ? m.lineage_refs : [];
  const icon = q === "ok" ? "OK" : q === "degraded" ? "WARN" : "ERR";
  const refsText = refs.length ? refs.join(" | ") : "—";
  el.innerHTML = `<div><strong>${icon}</strong> 数据质量：${esc(q)}</div><div class="screening-muted">schema=${esc(
    m.schema_name || "—",
  )} v${esc(m.schema_version || "—")} · trade_date=${esc(m.trade_date || "—")}</div><div class="screening-muted">lineage: ${esc(refsText)}</div>`;
}

function metricTone(metricKey, v) {
  const thresholds = (researchCache.view || {}).alert_thresholds || RESEARCH_ALERT_DEFAULTS;
  const t = thresholds[metricKey] || {};
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  if (metricKey === "hit_rate_5d_pct") {
    if (Number.isFinite(Number(t.bad_below)) && n < Number(t.bad_below)) return "tone-bad";
    if (Number.isFinite(Number(t.warn_below)) && n < Number(t.warn_below)) return "tone-warn";
    return "";
  }
  if (metricKey === "pause_events_count") {
    if (Number.isFinite(Number(t.bad_at_or_above)) && n >= Number(t.bad_at_or_above)) return "tone-bad";
    if (Number.isFinite(Number(t.warn_at_or_above)) && n >= Number(t.warn_at_or_above)) return "tone-warn";
    return "";
  }
  if (metricKey === "tail_recommended_count") {
    if (Number.isFinite(Number(t.warn_at_or_below)) && n <= Number(t.warn_at_or_below)) return "tone-warn";
  }
  return "";
}

function renderResearchPerformanceCards(effectStats) {
  const el = qs("researchPerformanceCards");
  if (!el) return;
  const s = effectStats || {};
  const perf = (researchCache.view || {}).performance_context || {};
  const asOf = perf.as_of || "—";
  const pct = (v, reason) => (v == null ? `待产出（${reason || "待上游任务产出"}）` : `${(Number(v) * 100).toFixed(1)}%`);
  const card = (k, v, tone) =>
    `<div class="kpi-card ${tone || ""}"><div class="kpi-label">${esc(k)}</div><div class="kpi-value">${esc(v)}</div></div>`;
  el.innerHTML = [
    card("夜盘候选数", s.nightly_candidate_count == null ? "—" : String(s.nightly_candidate_count), ""),
    card(
      "尾盘推荐数",
      s.tail_recommended_count == null ? "—" : String(s.tail_recommended_count),
      metricTone("tail_recommended_count", s.tail_recommended_count),
    ),
    card("范式池非空数", s.tail_pools_nonempty_count == null ? "—" : String(s.tail_pools_nonempty_count), ""),
    card(
      "5日命中率",
      pct(s.hit_rate_5d_pct, `周复盘指标缺失（weekly-selection-review，as_of=${asOf}）`),
      metricTone("hit_rate_5d_pct", s.hit_rate_5d_pct),
    ),
    card(
      "5日平均最大收益",
      pct(s.avg_max_return_5d_pct, `周复盘指标缺失（weekly-selection-review，as_of=${asOf}）`),
      "",
    ),
    card(
      "暂停事件数",
      s.pause_events_count == null ? "—" : String(s.pause_events_count),
      metricTone("pause_events_count", s.pause_events_count),
    ),
  ].join("");
}

function renderResearchHeatmap(rows) {
  const tbody = qs("researchHeatmapTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const list = Array.isArray(rows) ? rows : [];
  const max = list.reduce((m, x) => Math.max(m, Number(x?.count) || 0), 0) || 1;
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td colspan='3'>暂无板块热度数据</td>";
    tbody.appendChild(tr);
    return;
  }
  for (const r of list.slice(0, 12)) {
    const c = Number(r.count) || 0;
    const pct = Math.round((c / max) * 100);
    const tr = document.createElement("tr");
    const label = r.sector_name || "未标注";
    tr.title = `${label}：${c} 只（相对本表最大值的条形占比 ${pct}%）`;
    tr.innerHTML = `<td>${esc(label)}</td><td>${esc(c)}</td><td><div class="research-heat-bar" style="width:${pct}%"></div></td>`;
    tbody.appendChild(tr);
  }
}

function renderTaskMonitor(rows) {
  const tbody = qs("researchTaskMonitorTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td colspan='4'>暂无任务监控数据</td>";
    tbody.appendChild(tr);
    return;
  }
  for (const r of list) {
    const st = String(r.status || "unknown");
    const signalText = r.signal == null ? "待上游产出" : String(r.signal);
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(r.task_id || "")}</td><td><span class="research-status-pill ${esc(st)}">${esc(st)}</span></td><td>${esc(
      r.last_run || "—",
    )}</td><td>${esc(signalText)}</td>`;
    tbody.appendChild(tr);
  }
}

function renderFactorDiagnostics(rows) {
  const tbody = qs("researchFactorDiagTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td colspan='5'>暂无因子诊断数据</td>";
    tbody.appendChild(tr);
    return;
  }
  for (const r of list) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(r.name || "")}</td><td>${esc(r.ic_proxy ?? "—")}</td><td>${esc(
      r.hit_rate_top_bucket ?? "—",
    )}</td><td>${esc(r.sample_size ?? "—")}</td><td>${esc(r.stability ?? "—")}</td>`;
    tbody.appendChild(tr);
  }
}

function renderStrategyAttribution(attr) {
  const el = qs("researchAttribution");
  if (!el) return;
  const a = attr && typeof attr === "object" ? attr : {};
  const byParadigm = a.by_paradigm && typeof a.by_paradigm === "object" ? a.by_paradigm : {};
  const stage = a.by_task_stage && typeof a.by_task_stage === "object" ? a.by_task_stage : {};
  const gate = a.gate_impact && typeof a.gate_impact === "object" ? a.gate_impact : {};
  const pRows = Object.entries(byParadigm)
    .map(([k, v]) => `${k}: 推荐${v.recommendations ?? 0} 平均分${v.avg_score ?? "—"}`)
    .join(" | ");
  el.innerHTML = `<div><strong>按范式：</strong>${esc(pRows || "—")}</div><div><strong>按阶段：</strong>nightly=${
    esc((stage.nightly || {}).recommendations ?? "—")
  } / tail=${esc((stage.tail || {}).recommendations ?? "—")}</div><div><strong>门闸影响：</strong>stale_or_missing_tasks=${esc(
    gate.stale_or_missing_tasks ?? "—",
  )}</div>`;
}

function renderSimpleRows(tbodyId, rows, cols, emptyText) {
  const tbody = qs(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = "";
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="${cols.length}">${esc(emptyText || "暂无数据")}</td>`;
    tbody.appendChild(tr);
    return;
  }
  for (const r of list) {
    const tr = document.createElement("tr");
    tr.innerHTML = cols
      .map((c) => {
        const raw = typeof c.get === "function" ? c.get(r) : r?.[c.key];
        return `<td>${esc(raw == null ? "" : String(raw))}</td>`;
      })
      .join("");
    tbody.appendChild(tr);
  }
}

function renderResearchTaskPools(viewData) {
  const candidates = viewData?.candidates || {};
  const nightly = Array.isArray(candidates.nightly) ? candidates.nightly : [];
  const tailRecommended = Array.isArray(candidates.tail) ? candidates.tail : [];
  const pools = viewData?.tail_paradigm_pools || {};
  const symbolNameMap = new Map();
  const bindName = (rows) => {
    const list = Array.isArray(rows) ? rows : [];
    for (const row of list) {
      if (!row || typeof row !== "object") continue;
      const symbol = row.symbol == null ? "" : String(row.symbol).trim();
      if (!symbol) continue;
      const name = row.name ?? row.stock_name ?? row.security_name ?? row.display_name ?? "";
      const nameText = String(name || "").trim();
      if (nameText) symbolNameMap.set(symbol, nameText);
    }
  };
  bindName(nightly);
  bindName(tailRecommended);
  bindName(pools.fund_flow_follow || []);
  bindName(pools.tail_grab || []);
  bindName(pools.oversold_bounce || []);
  bindName(pools.sector_rotation || []);
  renderSimpleRows(
    "researchNightlyTbody",
    nightly.slice(0, 30),
    [
      { key: "symbol" },
      { get: (r) => r.name || r.stock_name || r.security_name || symbolNameMap.get(String(r.symbol || "").trim()) || "—" },
      { get: (r) => r.industry || "—" },
      { get: (r) => (r.score == null ? "—" : Number(r.score).toFixed(2)) },
    ],
    "暂无夜盘候选",
  );
  renderSimpleRows(
    "researchTailRecommendedTbody",
    tailRecommended.slice(0, 20),
    [
      { key: "symbol" },
      { key: "name" },
      { get: (r) => r.sector_name || "—" },
      { get: (r) => r.score ?? r.composite_score ?? "—" },
      { get: (r) => (Array.isArray(r.source_tags) ? r.source_tags.join(",") : "") },
    ],
    "暂无尾盘推荐",
  );
  const poolCols = [
    { key: "symbol" },
    { key: "name" },
    { get: (r) => r.sector_name || "—" },
    { get: (r) => r.paradigm_score ?? "—" },
  ];
  renderSimpleRows("researchPoolFundFlowTbody", pools.fund_flow_follow || [], poolCols, "暂无资金流追随池");
  renderSimpleRows("researchPoolTailGrabTbody", pools.tail_grab || [], poolCols, "暂无尾盘抢筹池");
  renderSimpleRows("researchPoolOversoldTbody", pools.oversold_bounce || [], poolCols, "暂无超跌反弹池");
  renderSimpleRows("researchPoolSectorRotTbody", pools.sector_rotation || [], poolCols, "暂无板块轮动池");
  const nightlyEmptyHint = qs("research-nightly-left");
  if (nightlyEmptyHint) {
    const nightlyCount = nightly.length;
    const td = ((viewData || {})._meta || {}).trade_date || "—";
    if (nightlyCount <= 0) {
      nightlyEmptyHint.innerHTML = `<h4 class="screening-h4">夜盘选股说明</h4><div class="small screening-muted">当前交易日 ${esc(
        td,
      )} 的夜盘候选为空。常见原因：该日夜盘任务未产出或被门闸拦截。可切换交易日查看历史有数据的审计结果。</div>`;
    } else {
      nightlyEmptyHint.innerHTML = `<h4 class="screening-h4">夜盘选股说明</h4><div class="small screening-muted">当前交易日 ${esc(
        td,
      )} 有 ${esc(nightlyCount)} 条夜盘候选，展示 \`nightly-stock-screening\` 只读结果。</div>`;
    }
  }
}

function collectResearchAnomalies() {
  const anomalies = [];
  const effect = researchCache.view?.effect_stats || {};
  const thresholds = researchCache.view?.alert_thresholds || RESEARCH_ALERT_DEFAULTS;
  const monitor = researchCache.view?.task_execution_monitor || [];
  const risk = researchCache.dashboard?.risk_snapshot || {};
  const events = Array.isArray(researchCache.timeline) ? researchCache.timeline : [];
  const hitRate = Number(effect.hit_rate_5d_pct);
  if (Number.isFinite(hitRate) && Number.isFinite(Number((thresholds.hit_rate_5d_pct || {}).warn_below)) && hitRate < Number((thresholds.hit_rate_5d_pct || {}).warn_below)) {
    anomalies.push({ kind: "效果", detail: `5日命中率偏低: ${(Number(effect.hit_rate_5d_pct) * 100).toFixed(1)}%` });
  }
  const pauseCount = Number(effect.pause_events_count);
  if (
    Number.isFinite(pauseCount) &&
    Number.isFinite(Number((thresholds.pause_events_count || {}).warn_at_or_above)) &&
    pauseCount >= Number((thresholds.pause_events_count || {}).warn_at_or_above)
  ) {
    anomalies.push({ kind: "门闸", detail: `暂停事件偏多: ${effect.pause_events_count}` });
  }
  if ((risk.emergency_pause || {}).active) {
    anomalies.push({ kind: "风控", detail: `紧急熔断已触发: ${(risk.emergency_pause || {}).reason || "未提供原因"}` });
  }
  for (const t of monitor) {
    if (t.status === "stale" || t.status === "missing") {
      anomalies.push({ kind: "任务", detail: `${t.task_id} 状态=${t.status} 最近运行=${t.last_run || "—"}` });
    }
  }
  for (const e of events) {
    if (e.quality_status === "degraded") {
      anomalies.push({ kind: "时间轴", detail: `${e.task_id || "unknown"} 数据降级: ${e.summary || "—"}` });
    }
  }
  return anomalies;
}

function renderResearchAnomalyDrawer() {
  const listEl = qs("researchAnomalyList");
  if (!listEl) return;
  const anomalies = collectResearchAnomalies();
  if (!anomalies.length) {
    listEl.innerHTML = `<div class="screening-muted">当前未发现超过阈值的异常。</div>`;
    return;
  }
  listEl.innerHTML = anomalies
    .map((a) => `<div class="research-anomaly-item"><strong>${esc(a.kind)}</strong>：${esc(a.detail)}</div>`)
    .join("");
}

function setResearchSubview(name) {
  const views = Array.from(document.querySelectorAll(".research-view[data-subview]"));
  for (const v of views) {
    v.classList.toggle("active", v.getAttribute("data-subview") === name);
  }
  const t1 = qs("subtab-research-overview");
  const t2 = qs("subtab-research-nightly");
  const t3 = qs("subtab-research-tail");
  const t4 = qs("subtab-research-rotation");
  const t5 = qs("subtab-research-six-index");
  if (t1) t1.setAttribute("aria-selected", String(name === "overview"));
  if (t2) t2.setAttribute("aria-selected", String(name === "nightly"));
  if (t3) t3.setAttribute("aria-selected", String(name === "tail"));
  if (t4) t4.setAttribute("aria-selected", String(name === "rotation"));
  if (t5) t5.setAttribute("aria-selected", String(name === "six-index"));

  const drawer = qs("researchAnomalyDrawer");
  if (drawer && name !== "overview") drawer.style.display = "none";
}

function renderRotationPanel(payload) {
  const ROTATION_UI_BUILD = "20260501-2028";
  const sumEl = qs("researchRotationSummary");
  const unifiedTbody = qs("researchRotationUnifiedTbody");
  const tbody = qs("researchRotationLegacyTbody");
  const secSumEl = qs("researchSectorRotationSummary");
  const secTbody = qs("researchSectorRotationLegacyTbody");
  if (unifiedTbody) unifiedTbody.innerHTML = "";
  if (tbody) tbody.innerHTML = "";
  if (secTbody) secTbody.innerHTML = "";
  const p = payload && typeof payload === "object" ? payload : {};
  const dq = p.data_quality && typeof p.data_quality === "object" ? p.data_quality : {};
  const gateObj = p.three_factor_context && typeof p.three_factor_context === "object" ? p.three_factor_context.gate || {} : {};
  const gateDisplay = gateObj.total_multiplier ?? gateObj.stage_multiplier ?? "—";
  const effEnv = p.sector_environment_effective && typeof p.sector_environment_effective === "object" ? p.sector_environment_effective : {};
  const effGate = effEnv.effective_gate ?? "—";
  const degradedReasons = Array.isArray(dq.degraded_reasons) ? dq.degraded_reasons : [];
  const warnings = Array.isArray(dq.warnings) ? dq.warnings : [];
  const errors = Array.isArray(dq.errors) ? dq.errors : [];
  const reasonText = [...degradedReasons, ...warnings, ...errors].filter(Boolean).join("；");
  const top = Array.isArray(p.top5) ? p.top5 : [];
  const recs = Array.isArray(p.recommendations) ? p.recommendations : [];
  const unifiedRaw = Array.isArray(p.unified_next_day) ? p.unified_next_day : [];
  const unified = unifiedRaw.length
    ? unifiedRaw
    : recs.map((r, idx) => ({
        rank: r.rank ?? idx + 1,
        etf_code: r.etf_code || r.symbol || "",
        etf_name: r.etf_name || "",
        sector: r.sector || "",
        unified_score: r.composite_score ?? r.score,
        components: {
          rps_20d: r.signals?.rps_20d,
          rps_5d: r.signals?.rps_5d,
          rps_change: r.signals?.rps_change,
          three_factor_score: null,
          volume_ratio: r.signals?.volume_ratio,
        },
        gate_effective: effGate,
        allocation_pct: r.allocation_pct,
        three_factor_missing: true,
        cautions: Array.isArray(r.cautions) ? r.cautions : [],
        explain_bullets: Array.isArray(r.explain_bullets) ? r.explain_bullets : [],
      }));
  const secEnv = p.sector_environment && typeof p.sector_environment === "object" ? p.sector_environment : {};
  const deriveGateFromRecs = () => {
    const vals = recs
      .map((r) => Number(r?.signals?.rps_20d))
      .filter((x) => Number.isFinite(x));
    if (!vals.length) return "UNKNOWN";
    const strongRatio = vals.filter((x) => x >= 85).length / vals.length;
    if (strongRatio > 0.3) return "GO";
    if (strongRatio > 0.1) return "CAUTION";
    return "STOP";
  };
  const secGateRaw = String(secEnv.gate || "").trim();
  const secGateDisplay = secGateRaw && secGateRaw !== "UNKNOWN" ? secGateRaw : (effGate && effGate !== "UNKNOWN" ? effGate : deriveGateFromRecs());
  const secReasonCodes = Array.isArray(secEnv.reason_codes) ? secEnv.reason_codes : [];
  const secReasonDisplay =
    secReasonCodes.length && secReasonCodes[0] !== "phase_a_no_environment_gate"
      ? secReasonCodes.join("；")
      : `ui_derived_from_recommendations:${secGateDisplay}`;
  const gateSource =
    secGateRaw && secGateRaw !== "UNKNOWN"
      ? "api.sector_environment.gate"
      : effGate && effGate !== "UNKNOWN"
      ? "api.sector_environment_effective.effective_gate"
      : "ui.derived_from_recommendations";
  const quality = String((p._meta || {}).quality_status || p.quality_status || "unknown");
  const displayDate = String(p.trade_date || (p._meta || {}).trade_date || "");
  const requestedDate = String(p._requested_trade_date || displayDate || "");
  const autoFallback = Boolean(p._auto_fallback_to_prev_trade_date);
  if (sumEl) {
    const rpsCountHint = recs.length < 5 ? `（低于目标5，可能受当日数据可用性影响）` : "";
    sumEl.innerHTML = `<div><strong>交易日</strong>：${esc(p.trade_date || (p._meta || {}).trade_date || "—")}</div>
      <div><strong>质量状态</strong>：${esc(quality)}</div>
      <div><strong>UI版本</strong>：${esc(ROTATION_UI_BUILD)}</div>
      <div><strong>三维门闸（乘子）</strong>：${esc(gateDisplay)}</div>
      <div><strong>合成环境门闸</strong>：${esc(effGate)}</div>
      <div><strong>RPS条数</strong>：${esc(recs.length)}${esc(rpsCountHint)}</div>
      <div><strong>降级说明</strong>：${esc(reasonText || "无")}</div>`;
    if (autoFallback && requestedDate && displayDate && requestedDate !== displayDate) {
      sumEl.innerHTML += `<div><strong>非交易日回退</strong>：当前为非交易日/低可用日，已自动从 ${esc(
        requestedDate,
      )} 回退到上一交易日 ${esc(displayDate)}</div>`;
    }
  }
  if (secSumEl) {
    secSumEl.innerHTML = `<div><strong>插件环境 gate</strong>：${esc(secGateDisplay || "—")}</div>
      <div><strong>reason_codes</strong>：${esc(secReasonDisplay || "无")}</div>
      <div><strong>gate_source</strong>：${esc(gateSource)}</div>`;
  }

  if (unifiedTbody) {
    if (!unified.length) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td colspan='13'>暂无统一轮动建议</td>";
      unifiedTbody.appendChild(tr);
    } else {
      for (const r of unified) {
        const comp = r.components && typeof r.components === "object" ? r.components : {};
        const code = String(r.etf_code || "");
        const name = r.etf_name || ROTATION_ETF_NAME_MAP[code] || "—";
        const cautions = Array.isArray(r.cautions) ? r.cautions.join("；") : "";
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${esc(r.rank ?? "—")}</td>
          <td>${esc(code)}</td>
          <td>${esc(name)}</td>
          <td>${esc(r.sector || "—")}</td>
          <td>${esc(r.unified_score ?? "—")}</td>
          <td>${esc(comp.rps_20d ?? "—")}</td>
          <td>${esc(comp.rps_5d ?? "—")}</td>
          <td>${esc(comp.rps_change ?? "—")}</td>
          <td>${esc(comp.three_factor_score ?? "—")}</td>
          <td>${esc(r.gate_effective ?? "—")}</td>
          <td>${esc(r.allocation_pct ?? "—")}</td>
          <td>${esc(r.three_factor_missing ? "是" : "否")}</td>
          <td>${esc(cautions || "—")}</td>`;
        unifiedTbody.appendChild(tr);
      }
    }
  }

  const bulletEl = qs("researchRotationUnifiedBullets");
  if (bulletEl) {
    bulletEl.innerHTML = "";
    let anyBullets = false;
    const fallbackBullets = (r) => {
      const comp = r.components && typeof r.components === "object" ? r.components : {};
      const b = [];
      if (comp.rps_20d != null || comp.rps_5d != null || comp.rps_change != null) {
        b.push(`RPS20=${comp.rps_20d ?? "—"} / RPS5=${comp.rps_5d ?? "—"} / Δ=${comp.rps_change ?? "—"}`);
      }
      if (r.gate_effective) b.push(`门闸=${r.gate_effective}`);
      if (comp.volume_ratio != null) b.push(`量比=${comp.volume_ratio}`);
      return b;
    };
    for (const r of unified) {
      const bulletsRaw = Array.isArray(r.explain_bullets) ? r.explain_bullets : [];
      const bullets = bulletsRaw.length ? bulletsRaw : fallbackBullets(r);
      if (!bullets.length) continue;
      anyBullets = true;
      const li = document.createElement("li");
      li.style.marginBottom = "4px";
      li.innerHTML = `<strong>${esc(String(r.etf_code || ""))}</strong>：${esc(bullets.join(" / "))}`;
      bulletEl.appendChild(li);
    }
    if (!anyBullets) {
      const li = document.createElement("li");
      li.className = "screening-muted";
      li.textContent = "暂无可解释要点";
      bulletEl.appendChild(li);
    }
  }

  if (!tbody) return;
  if (!top.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td colspan='6'>暂无轮动推荐（legacy）</td>";
    tbody.appendChild(tr);
  }
  for (const r of top) {
    const tf = r.three_factor || {};
    const symbol = String(r.symbol || "");
    const name = r.name || ROTATION_ETF_NAME_MAP[symbol] || "—";
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(symbol)}</td><td>${esc(name)}</td><td>${esc(r.score ?? r.composite_score ?? "—")}</td><td>${esc(
      tf.momentum_score ?? "—",
    )}</td><td>${esc(tf.capital_resonance_score ?? "—")}</td><td>${esc(tf.environment_gate ?? "—")}</td>`;
    tbody.appendChild(tr);
  }

  if (!secTbody) return;
  if (!recs.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td colspan='6'>暂无行业ETF建议（RPS，legacy）</td>";
    secTbody.appendChild(tr);
    return;
  }
  for (const r of recs) {
    const tr = document.createElement("tr");
    const etf = String(r.etf_code || r.symbol || "");
    const name = r.etf_name || ROTATION_ETF_NAME_MAP[etf] || "—";
    const cautions = Array.isArray(r.cautions) ? r.cautions.join("；") : "";
    tr.innerHTML = `<td>${esc(r.rank ?? "—")}</td>
      <td>${esc(r.sector || "—")}</td>
      <td>${esc(etf)}(${esc(name)})</td>
      <td>${esc(r.composite_score ?? r.score ?? "—")}</td>
      <td>${esc(r.allocation_pct ?? "—")}%</td>
      <td>${esc(cautions || "—")}</td>`;
    secTbody.appendChild(tr);
  }
}

async function loadResearch(tradeDateOverride = "") {
  const status = qs("researchStatus");
  if (status) status.textContent = "加载中…";
  try {
    const hist = await jgetWithFallback("/api/semantic/trade_dates", "/api/tail_screening/history");
    const dates = Array.isArray(hist.data)
      ? hist.data.map((x) => (typeof x === "string" ? x : x.date)).filter(Boolean)
      : [];
    const rotationDatesResp = await jgetWithFallback("/api/semantic/rotation_trade_dates", "");
    const rotationDates = Array.isArray(rotationDatesResp.data) ? rotationDatesResp.data.filter(Boolean) : [];
    const latestRotationDate = rotationDates.length
      ? rotationDates.reduce((acc, d) => (String(d) > String(acc) ? d : acc), "")
      : "";

    const metricsResp = await jgetWithFallback(
      tradeDateOverride
        ? `/api/semantic/research_metrics?trade_date=${encodeURIComponent(tradeDateOverride)}&window=5`
        : "/api/semantic/research_metrics?window=5",
      "/api/semantic/dashboard",
    );
    const metricsData = metricsResp.data || {};
    let tradeDate = tradeDateOverride || latestRotationDate || (metricsData?._meta || {}).trade_date || "";
    if (!tradeDate && dates.length) tradeDate = dates[dates.length - 1];
    const diagnosticsResp = await jgetWithFallback(
      `/api/semantic/research_diagnostics?trade_date=${encodeURIComponent(tradeDate)}&window=5`,
      `/api/semantic/timeline?trade_date=${encodeURIComponent(tradeDate)}`,
    );
    const diagnosticsData = diagnosticsResp.data || {};
    const dashboard = await jgetWithFallback("/api/semantic/dashboard", "/api/screening/summary");
    const data = dashboard.data || {};
    const factorResp = await jgetWithFallback(
      `/api/semantic/factor_diagnostics?trade_date=${encodeURIComponent(tradeDate)}&period=week`,
      "",
    );
    const attributionResp = await jgetWithFallback(
      `/api/semantic/strategy_attribution?trade_date=${encodeURIComponent(tradeDate)}`,
      "",
    );
    const view = tradeDate
      ? await jgetWithFallback(
          `/api/semantic/screening_view?trade_date=${encodeURIComponent(tradeDate)}`,
          `/api/screening/by-date?date=${encodeURIComponent(tradeDate)}`,
        )
      : { data: {} };
    let rotation = await jgetWithFallback(
      tradeDate
        ? `/api/semantic/rotation_latest?trade_date=${encodeURIComponent(tradeDate)}`
        : "/api/semantic/rotation_latest",
      "",
    );
    // Non-trading-day fallback:
    // when user did not explicitly pick a date and current snapshot has too few RPS rows,
    // fall back to the previous available rotation trade date for a more stable default view.
    if (!tradeDateOverride && rotationDates.length > 1) {
      const curRecs = Array.isArray((rotation.data || {}).recommendations) ? rotation.data.recommendations : [];
      if (curRecs.length > 0 && curRecs.length < 5) {
        const sorted = rotationDates.slice().sort();
        const prev = sorted.filter((d) => String(d) < String(tradeDate)).pop();
        if (prev) {
          const prevRot = await jgetWithFallback(`/api/semantic/rotation_latest?trade_date=${encodeURIComponent(prev)}`, "");
          const prevRecs = Array.isArray((prevRot.data || {}).recommendations) ? prevRot.data.recommendations : [];
          if (prevRecs.length >= curRecs.length) {
            rotation = prevRot;
            if (!rotation.data || typeof rotation.data !== "object") rotation.data = {};
            rotation.data._requested_trade_date = tradeDate;
            rotation.data._auto_fallback_to_prev_trade_date = true;
            tradeDate = prev;
          }
        }
      }
    }
    const sixIndexDatesResp = await jget("/api/semantic/six_index_next_day_trade_dates");
    const sixIndexDates = Array.isArray(sixIndexDatesResp.data) ? sixIndexDatesResp.data.filter(Boolean) : [];
    // "默认选中最新交易日"必须做成与数组顺序无关的选择（避免出现显示最旧日期）。
    // YYYY-MM-DD 字典序与时间序一致，因此直接取最大值即可。
    const sixIndexLatestTradeDate = sixIndexDates.reduce(
      (acc, d) => (String(d) > String(acc) ? d : acc),
      "",
    );
    const sixIndexTradeDate =
      (tradeDateOverride && sixIndexDates.includes(tradeDateOverride) ? tradeDateOverride : "") ||
      (tradeDate && sixIndexDates.includes(tradeDate) ? tradeDate : "") ||
      sixIndexLatestTradeDate;
    const sixIndexResp = await jget(
      sixIndexTradeDate
        ? `/api/semantic/six_index_next_day?trade_date=${encodeURIComponent(sixIndexTradeDate)}`
        : "/api/semantic/six_index_next_day",
    );
    const viewData = view.data || {};
    const rotationData = rotation.data || {};
    const sixIndexData = sixIndexResp.data || {};
    const sent = metricsData.sentiment_trend || {};
    const market = data.market_state || {};
    const risk = data.risk_snapshot || {};
    renderResearchQuality(metricsData._meta || {});
    renderResearchKV("researchSentiment", [
      { k: "综合得分", v: sent.current_score },
      { k: "阶段", v: sent.current_stage },
      { k: "分歧度", v: sent.dispersion },
      { k: "趋势变化", v: Array.isArray(sent.trend_5d) ? sent.trend_5d.join(", ") : "—" },
      { k: "质量", v: (metricsData._meta || {}).quality_status || "unknown" },
    ]);
    renderResearchKV("researchMarketState", [
      { k: "市场状态", v: market.regime },
      { k: "仓位上限", v: market.position_ceiling },
      { k: "门闸", v: market.pause_status ? "触发" : "正常" },
    ]);
    renderResearchKV("researchRiskSnapshot", [
      { k: "紧急熔断", v: (risk.emergency_pause || {}).active ? "是" : "否" },
      { k: "门闸原因", v: risk.latest_gate_reason || "—" },
      { k: "极端告警", v: risk.extreme_alert_count ?? "—" },
    ]);
    renderResearchPerformanceCards({
      ...(viewData.effect_stats || {}),
      ...(metricsData.screening_effectiveness || {}),
    });
    renderResearchHeatmap(viewData.sector_rotation_heatmap || []);
    renderTaskMonitor(viewData.task_execution_monitor || []);
    renderFactorDiagnostics((factorResp.data || {}).factors || []);
    renderStrategyAttribution((attributionResp.data || {}).attribution || {});
    renderResearchTaskPools(viewData);
    renderResearchTop(data.top_recommendations || []);
    renderRotationPanel(rotationData);
    renderSixIndexMeta(sixIndexData);
    renderSixIndexSummaryCards(sixIndexData);
    renderSixIndexCards(sixIndexData);
    const pick = qs("researchDatePick");
    if (pick) {
      pick.innerHTML = dates
        .slice()
        .reverse()
        .map((d) => `<option value="${esc(d)}">${esc(d)}</option>`)
        .join("");
      pick.value = tradeDate;
    }
    const nightlyPick = qs("researchNightlyDatePick");
    if (nightlyPick) {
      nightlyPick.innerHTML = dates
        .slice()
        .reverse()
        .map((d) => `<option value="${esc(d)}">${esc(d)}</option>`)
        .join("");
      nightlyPick.value = tradeDate;
    }
    const tailPick = qs("researchTailDatePick");
    if (tailPick) {
      tailPick.innerHTML = dates
        .slice()
        .reverse()
        .map((d) => `<option value="${esc(d)}">${esc(d)}</option>`)
        .join("");
      tailPick.value = tradeDate;
    }
    const rotationPick = qs("researchRotationDatePick");
    if (rotationPick) {
      const opts = (rotationDates.length ? rotationDates : dates).slice().reverse();
      rotationPick.innerHTML = opts
        .slice()
        .map((d) => `<option value="${esc(d)}">${esc(d)}</option>`)
        .join("");
      rotationPick.value = tradeDate;
    }
    const sixIndexPick = qs("researchSixIndexDatePick");
    if (sixIndexPick) {
      sixIndexPick.innerHTML = sixIndexDates
        .slice()
        .reverse()
        .map((d) => `<option value="${esc(d)}">${esc(d)}</option>`)
        .join("");
      sixIndexPick.value = sixIndexData.trade_date || sixIndexTradeDate || "";
    }
    if (tradeDate) {
      const timeline = await jgetWithFallback(`/api/semantic/timeline?trade_date=${encodeURIComponent(tradeDate)}`, "");
      const events = (timeline.data || {}).events || (diagnosticsData.diagnostics || {}).degraded_events || [];
      researchCache = { dashboard: data, view: viewData, timeline: events };
      renderResearchTimeline(events);
      renderSubTimeline("researchNightlyTimeline", events, !!qs("researchNightlyTimelineOnlyAnomaly")?.checked);
      renderSubTimeline("researchTailTimeline", events, !!qs("researchTailTimelineOnlyAnomaly")?.checked);
      renderSubTimeline("researchRotationTimeline", events, false);
      renderResearchAnomalyDrawer();
    } else {
      researchCache = { dashboard: data, view: viewData, timeline: [] };
      renderResearchTimeline([]);
      renderSubTimeline("researchNightlyTimeline", [], false);
      renderSubTimeline("researchTailTimeline", [], false);
      renderSubTimeline("researchRotationTimeline", [], false);
      renderResearchAnomalyDrawer();
    }
    if (status) status.textContent = "已更新";
  } catch (e) {
    if (status) status.textContent = String(e?.message || e);
  }
}

qs("tab-screening")?.addEventListener("click", () => {
  setView("screening");
  setScreeningSubview("nightly");
  loadScreening();
});
qs("tab-research")?.addEventListener("click", () => {
  setView("research");
  setResearchSubview("overview");
  loadResearch();
});

qs("btnScreeningRefresh")?.addEventListener("click", () => loadScreening());

qs("screeningDatePick")?.addEventListener("change", (e) => {
  const v = e.target?.value;
  if (v) loadDateArtifact(v);
});

qs("screeningMetricsSource")?.addEventListener("change", () => renderMetricsFromCache());
qs("subtab-screening-nightly")?.addEventListener("click", () => {
  setScreeningSubview("nightly");
  loadScreening();
});
qs("subtab-screening-tail")?.addEventListener("click", () => {
  setScreeningSubview("tail");
  loadTailScreening();
});
qs("btnTailScreeningRefresh")?.addEventListener("click", () => loadTailScreening());
qs("tailScreeningDatePick")?.addEventListener("change", (e) => {
  const v = e.target?.value;
  if (v) loadTailByDate(v);
});
qs("btnResearchRefresh")?.addEventListener("click", () => loadResearch());
qs("researchDatePick")?.addEventListener("change", async (e) => {
  const v = e.target?.value;
  if (!v) return;
  await loadResearch(v);
});
qs("researchTimelineOnlyAnomaly")?.addEventListener("change", () => {
  renderResearchTimeline(researchCache.timeline);
});
qs("researchNightlyDatePick")?.addEventListener("change", async (e) => {
  const v = e.target?.value || "";
  if (!v) return;
  await loadResearch(v);
  setResearchSubview("nightly");
});
qs("researchTailDatePick")?.addEventListener("change", async (e) => {
  const v = e.target?.value || "";
  if (!v) return;
  await loadResearch(v);
  setResearchSubview("tail");
});
qs("researchNightlyTimelineOnlyAnomaly")?.addEventListener("change", async () => {
  const v = qs("researchNightlyDatePick")?.value || "";
  await loadTimelineInto(v, "researchNightlyTimeline", !!qs("researchNightlyTimelineOnlyAnomaly")?.checked);
});
qs("researchTailTimelineOnlyAnomaly")?.addEventListener("change", async () => {
  const v = qs("researchTailDatePick")?.value || "";
  await loadTimelineInto(v, "researchTailTimeline", !!qs("researchTailTimelineOnlyAnomaly")?.checked);
});
qs("subtab-research-overview")?.addEventListener("click", () => setResearchSubview("overview"));
qs("subtab-research-nightly")?.addEventListener("click", () => setResearchSubview("nightly"));
qs("subtab-research-tail")?.addEventListener("click", () => setResearchSubview("tail"));
qs("subtab-research-rotation")?.addEventListener("click", () => setResearchSubview("rotation"));
qs("subtab-research-six-index")?.addEventListener("click", () => setResearchSubview("six-index"));
qs("btnResearchSixIndexCopy")?.addEventListener("click", async () => {
  const btn = qs("btnResearchSixIndexCopy");
  const text = buildSixIndexClipboardText(researchSixIndexSnapshot);
  if (!text.trim() || text.includes("交易日: —")) {
    if (btn) btn.textContent = "暂无可复制内容";
    setTimeout(() => {
      if (btn) btn.textContent = "复制当日摘要";
    }, 1200);
    return;
  }
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    if (btn) btn.textContent = "已复制";
  } catch (_) {
    if (btn) btn.textContent = "复制失败";
  }
  setTimeout(() => {
    if (btn) btn.textContent = "复制当日摘要";
  }, 1200);
});
qs("researchRotationDatePick")?.addEventListener("change", async (e) => {
  const v = e.target?.value || "";
  if (!v) return;
  await loadResearch(v);
  setResearchSubview("rotation");
});
qs("researchSixIndexDatePick")?.addEventListener("change", async (e) => {
  const v = e.target?.value || "";
  if (!v) return;
  await loadResearch(v);
  setResearchSubview("six-index");
});
qs("btnResearchAnomalyDrawer")?.addEventListener("click", () => {
  const el = qs("researchAnomalyDrawer");
  if (!el) return;
  renderResearchAnomalyDrawer();
  el.style.display = "block";
});
qs("btnResearchAnomalyClose")?.addEventListener("click", () => {
  const el = qs("researchAnomalyDrawer");
  if (!el) return;
  el.style.display = "none";
});
