import { jget } from "./api.js";
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
    const r = await jget(`/api/screening/by-date?date=${encodeURIComponent(dateStr)}`);
    if (!r.success) {
      if (status) status.textContent = r.message || "加载失败";
      renderAuditFromArtifact(null);
      renderTable([]);
      renderRunSnapshot(null);
      return;
    }
    const art = r.data;
    renderAuditFromArtifact(art);
    const rows = art && art.screening && art.screening.data;
    renderTable(Array.isArray(rows) ? rows : []);
    renderRunSnapshot(art);
    if (status) status.textContent = `已选审计日: ${dateStr}`;
  } catch (e) {
    if (status) status.textContent = String(e?.message || e);
  }
}

async function loadScreening() {
  const status = qs("screeningStatus");
  if (status) status.textContent = "加载中…";
  try {
    const r = await jget("/api/screening/summary");
    if (!r.success || !r.data) {
      if (status) status.textContent = r.message || "加载页面摘要失败";
      return;
    }
    const data = r.data;
    cachedSummary = data;
    renderPhaseHint();
    renderBanner(data);
    renderLeft(data);
    renderWatchlist(data.watchlist || {});
    renderMetricsFromCache();

    const hist = await jget("/api/screening/history");
    const dates = (hist.data || []).map((x) => x.date).filter(Boolean);
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
      renderTable(data.latest_screening_rows || []);
      renderAuditFromArtifact(data.latest_artifact || null);
      renderRunSnapshot(data.latest_artifact || null);
      if (status) status.textContent = "暂无历史审计文件，请先完成夜盘落盘。";
    }
  } catch (e) {
    if (status) status.textContent = String(e?.message || e);
  }
}

qs("tab-screening")?.addEventListener("click", () => {
  setView("screening");
  loadScreening();
});

qs("btnScreeningRefresh")?.addEventListener("click", () => loadScreening());

qs("screeningDatePick")?.addEventListener("change", (e) => {
  const v = e.target?.value;
  if (v) loadDateArtifact(v);
});

qs("screeningMetricsSource")?.addEventListener("change", () => renderMetricsFromCache());
