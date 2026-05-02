import { jget } from "./api.js";
import { setView } from "./app.js";

function qs(id) {
  return document.getElementById(id);
}

function currentOpsSubview() {
  const t1 = qs("subtab-ops-exec");
  const t2 = qs("subtab-ops-collect");
  const t3 = qs("subtab-ops-health");
  if (t1?.getAttribute("aria-selected") === "true") return "exec";
  if (t2?.getAttribute("aria-selected") === "true") return "collect";
  if (t3?.getAttribute("aria-selected") === "true") return "health";
  return "exec";
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setOpsSubview(name) {
  const exec = qs("ops-exec-view");
  const collect = qs("ops-collect-view");
  const health = qs("ops-health-view");
  const isExec = name === "exec";
  const isCollect = name === "collect";
  const isHealth = name === "health";
  if (exec) exec.classList.toggle("active", isExec);
  if (collect) collect.classList.toggle("active", isCollect);
  if (health) health.classList.toggle("active", isHealth);
  const t1 = qs("subtab-ops-exec");
  const t2 = qs("subtab-ops-collect");
  const t3 = qs("subtab-ops-health");
  if (t1) t1.setAttribute("aria-selected", String(isExec));
  if (t2) t2.setAttribute("aria-selected", String(isCollect));
  if (t3) t3.setAttribute("aria-selected", String(isHealth));
}

function openOpsDetailModal({ title, meta, jsonText }) {
  const modal = qs("opsDetailModal");
  if (!modal) return;
  const t = qs("opsDetailTitle");
  const m = qs("opsDetailMeta");
  const pre = qs("opsDetailJson");
  if (t) t.textContent = title || "任务详情";
  if (m) m.innerHTML = meta || "";
  if (pre) pre.textContent = jsonText || "";
  modal.classList.add("active");
}

function closeOpsDetailModal() {
  const modal = qs("opsDetailModal");
  if (!modal) return;
  modal.classList.remove("active");
}

function wireOpsDetailModal() {
  qs("btnOpsDetailClose")?.addEventListener("click", () => closeOpsDetailModal());
  qs("opsDetailModal")?.addEventListener("click", (e) => {
    if (e?.target && e.target.id === "opsDetailModal") closeOpsDetailModal();
  });
  qs("btnOpsDetailCopy")?.addEventListener("click", async () => {
    const pre = qs("opsDetailJson");
    const txt = pre?.textContent || "";
    if (!txt) return;
    try {
      await navigator.clipboard.writeText(txt);
    } catch {
      // ignore clipboard failures
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeOpsDetailModal();
  });
}

function parseSummaryPayload(summary) {
  if (!summary) return {};
  if (typeof summary === "object") return summary;
  const raw = String(summary || "").trim();
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    const i = raw.indexOf("{");
    if (i >= 0) {
      try {
        return JSON.parse(raw.slice(i));
      } catch {
        return {};
      }
    }
    return {};
  }
}

function compactReasons(value) {
  if (Array.isArray(value)) {
    return value.map((x) => String(x || "").trim()).filter(Boolean).join(",");
  }
  if (typeof value === "string") return value;
  return "";
}

function buildHealthIndex(rows) {
  const out = new Map();
  const src = Array.isArray(rows) ? rows : [];
  for (const r of src) {
    const taskId = String(r?.task_id || "");
    if (!taskId) continue;
    const summaryObj = parseSummaryPayload(r?.summary);
    const dataObj = summaryObj && typeof summaryObj.data === "object" ? summaryObj.data : {};
    const readiness = dataObj && typeof dataObj.data_readiness === "object" ? dataObj.data_readiness : {};
    const degradedReasons = compactReasons(readiness?.degraded_reasons || summaryObj?.degraded_reasons || r?.degraded_reasons);
    out.set(taskId, {
      run_quality: String(r?.run_quality || summaryObj?.run_quality || ""),
      failure_code: String(summaryObj?.failure_code || r?.failure_code || ""),
      duration_ms: Number(r?.duration_ms || 0),
      degraded_reasons: degradedReasons,
      execution_status: String(r?.execution_status || ""),
      data_quality_status: String(r?.data_quality_status || ""),
      data_quality_reasons: compactReasons(r?.data_quality_reasons),
      summaryObj,
    });
  }
  return out;
}

function renderRows(tbodyId, rows, healthIndex) {
  const tbody = qs(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = "";
  const onlyIssues = !!qs("opsOnlyIssues")?.checked;
  const src = Array.isArray(rows) ? rows : [];
  const list = onlyIssues
    ? src.filter((r) => {
        const q = String(r?.quality_status || "");
        const s = String(r?.last_run_status || "");
        const hx = healthIndex.get(String(r?.task_id || "")) || {};
        const ex = String(hx.execution_status || "");
        const dq = String(hx.data_quality_status || "");
        return q === "degraded" || s === "error" || ex === "error" || dq === "degraded" || Number(r?.consecutive_errors || 0) > 0;
      })
    : src;
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td colspan='11'>暂无事件</td>";
    tbody.appendChild(tr);
    return;
  }
  for (const r of list) {
    const tr = document.createElement("tr");
    const hx = healthIndex.get(String(r.task_id || "")) || {};
    const q = String(r.quality_status || "");
    const qLabel = String(hx.data_quality_status || q || "ok");
    const qStyle = qLabel === "degraded" ? " style='color:#f7c88a;font-weight:600;'" : "";
    const status = String(hx.execution_status || r.status || r.last_run_status || "");
    const statusStyle = status === "error" ? " style='color:#ff9a9a;font-weight:600;'" : (status === "ok" ? " style='color:#a7f3d0;'" : "");
    const nameAddon = r.audit_domain === "nikkei225_etf_monitor"
      ? ` <span class="chip">nikkei审计:${esc(r.monitor_group || "")}</span>`
      : (r.audit_domain === "nasdaq100_etf_monitor"
          ? ` <span class="chip">nasdaq审计:${esc(r.monitor_group || "")}</span>`
          : "");
    const runQuality = String(hx.run_quality || "");
    const runStyle = runQuality === "error"
      ? " style='color:#ff9a9a;font-weight:600;'"
      : (runQuality && runQuality !== "ok_full" ? " style='color:#f7c88a;font-weight:600;'" : "");
    const failureCode = String(hx.failure_code || "");
    const failStyle = failureCode && failureCode !== "none" ? " style='color:#ffb0b0;'" : "";
    const duration = Number(hx.duration_ms || 0);
    const reason = String(hx.data_quality_reasons || hx.degraded_reasons || "");
    const lineage = Array.isArray(r.lineage_refs) ? r.lineage_refs.slice(0, 2).join(" | ") : "";
    tr.innerHTML = `<td>${esc(r.task_id || "")}</td><td>${esc(r.name || "")}${nameAddon}</td><td>${esc(r.schedule || "")}</td><td${statusStyle}>${esc(
      status,
    )}</td><td${qStyle}>${esc(qLabel)}</td><td${runStyle}>${esc(runQuality || "—")}</td><td${failStyle}>${esc(
      failureCode || "—",
    )}</td><td>${duration > 0 ? esc(duration) : "—"}</td><td>${esc(reason || "—")}</td><td>${esc(
      lineage || "—",
    )}</td><td>${esc((r.tools_allow || []).join(","))}</td>`;
    tbody.appendChild(tr);
  }
}

function renderHealthRows(tbodyId, rows) {
  const tbody = qs(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = "";
  const onlyIssues = !!qs("opsOnlyIssues")?.checked;
  const src = Array.isArray(rows) ? rows : [];
  const base = onlyIssues
    ? src.filter((r) => {
      const q = String(r?.data_quality_status || r?.quality_status || "");
      const ex = String(r?.execution_status || "");
      return q === "degraded" || ex === "error";
    })
    : src;
  const list = [...base].sort((a, b) => String(a?.task_id || "").localeCompare(String(b?.task_id || "")));
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td colspan='13'>暂无事件</td>";
    tbody.appendChild(tr);
    return;
  }
  const fmtMs = (ms) => {
    const n = Number(ms);
    if (!Number.isFinite(n) || n <= 0) return "";
    return new Date(n).toLocaleString();
  };
  const mkLogCell = (r) => {
    const p = String(r.run_log_path || "").trim();
    const t = fmtMs(r.last_error_at_ms);
    const text = t ? `${p} @ ${t}` : p;
    if (!p) return "";
    return `<button type="button" class="small" data-log-path="${esc(p)}" title="点击复制日志路径">${esc(text)}</button>`;
  };
  for (const r of list) {
    const tr = document.createElement("tr");
    tr.classList.add("clickable");
    tr.setAttribute("data-task-id", String(r.task_id || ""));
    const q = String(r.data_quality_status || r.quality_status || "");
    const qLabel = q || "ok";
    const qStyle = qLabel === "degraded" ? " style='color:#f7c88a;font-weight:600;'" : "";
    const exStatus = String(r.execution_status || r.last_run_status || "");
    const exStyle = exStatus === "error" ? " style='color:#ff9a9a;font-weight:600;'" : (exStatus === "ok" ? " style='color:#a7f3d0;'" : "");
    const runQuality = String(r.run_quality || "");
    const runStyle = runQuality === "error"
      ? " style='color:#ff9a9a;font-weight:600;'"
      : (runQuality && runQuality !== "ok_full" ? " style='color:#f7c88a;font-weight:600;'" : "");
    const err = String(r.error || "").trim();
    const errShort = err.length > 140 ? `${err.slice(0, 140)}...` : err;
    const summaryObj = parseSummaryPayload(r.summary);
    const failureCode = String(summaryObj.failure_code || r.failure_code || "");
    const failStyle = failureCode && failureCode !== "none" ? " style='color:#ffb0b0;'" : "";
    const reasons = compactReasons(
      r.data_quality_reasons
        || summaryObj.data_quality_reasons
        || summaryObj.data_quality_reason
        || summaryObj.reasons
        || summaryObj.degraded_reasons
        || r.degraded_reasons,
      (summaryObj.data && summaryObj.data.data_readiness && summaryObj.data.data_readiness.degraded_reasons)
        || "",
    );
    const dur = Number(r.duration_ms || 0);
    tr.innerHTML = `<td>${esc(r.task_id || "")}</td><td>${esc(r.name || "")}</td><td>${esc(r.schedule || "")}</td><td>${esc(
      r.last_run_status || "",
    )}</td><td${qStyle}>${esc(qLabel)}</td><td${exStyle}>${esc(exStatus || "—")}</td><td${runStyle}>${esc(
      runQuality || "—",
    )}</td><td${failStyle}>${esc(
      failureCode || "—",
    )}</td><td>${dur > 0 ? esc(dur) : "—"}</td><td>${esc(reasons || "—")}</td><td>${esc(errShort)}</td><td>${esc(
      r.repair_hint || "",
    )}</td><td>${mkLogCell(r)}</td>`;
    tbody.appendChild(tr);
  }
  tbody.querySelectorAll("button[data-log-path]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const path = btn.getAttribute("data-log-path") || "";
      if (!path) return;
      try {
        await navigator.clipboard.writeText(path);
        const old = btn.textContent;
        btn.textContent = "已复制";
        setTimeout(() => {
          btn.textContent = old;
        }, 1200);
      } catch {
        // ignore clipboard failures in unsupported contexts
      }
    });
  });

  tbody.querySelectorAll("tr[data-task-id]").forEach((tr) => {
    tr.addEventListener("click", async (e) => {
      // Clicking the "log path" copy button should not open details.
      if (e?.target && String(e.target.tagName || "").toLowerCase() === "button") return;
      const tid = tr.getAttribute("data-task-id") || "";
      if (!tid) return;
      try {
        const r = await jget(`/api/semantic/ops_run_detail?task_id=${encodeURIComponent(tid)}&limit=80`);
        const d = r.data || {};
        const lf = d.last_finished || {};
        const status = String((lf && lf.status) || "");
        const ts = lf && lf.ts ? new Date(Number(lf.ts)).toLocaleString() : "";
        const dur = lf && lf.durationMs ? `${lf.durationMs}ms` : "";
        const meta = `<span class="chip">status:${esc(status || "—")}</span> <span class="chip">ts:${esc(ts || "—")}</span> <span class="chip">dur:${esc(
          dur || "—",
        )}</span> <span class="chip">log:${esc(d.run_log_path || "")}</span>`;
        openOpsDetailModal({
          title: `运维任务详情：${tid}`,
          meta,
          jsonText: JSON.stringify(d, null, 2),
        });
      } catch (err) {
        openOpsDetailModal({
          title: `运维任务详情：${tid}`,
          meta: `<span class="warn">加载失败</span> ${esc(String(err?.message || err))}`,
          jsonText: "",
        });
      }
    });
  });
}

function calcDurationP95(rows) {
  const arr = (Array.isArray(rows) ? rows : [])
    .map((x) => Number(x?.duration_ms || 0))
    .filter((x) => Number.isFinite(x) && x > 0)
    .sort((a, b) => a - b);
  if (!arr.length) return 0;
  const idx = Math.min(arr.length - 1, Math.max(0, Math.round((arr.length - 1) * 0.95)));
  return arr[idx];
}

function parseRunQualityFromSummary(summary) {
  const obj = parseSummaryPayload(summary);
  const rq = String(obj?.run_quality || "").trim();
  if (rq) return rq;
  return "";
}

function normalizeRunQuality(raw, fallbackStatus) {
  const rq = String(raw || "").trim();
  if (rq) return rq;
  const st = String(fallbackStatus || "").trim().toLowerCase();
  if (st === "ok") return "unknown";
  if (st === "error") return "error";
  return "unknown";
}

async function loadBaseline3dMetrics(taskRows) {
  const tasks = (Array.isArray(taskRows) ? taskRows : [])
    .map((x) => String(x?.task_id || "").trim())
    .filter(Boolean);
  if (!tasks.length) {
    return { p95: 0, okFullRatio: 0, sampleRuns: 0 };
  }
  const nowMs = Date.now();
  const floorMs = nowMs - 3 * 24 * 3600 * 1000;
  const allDurations = [];
  let allRuns = 0;
  let okFullRuns = 0;
  let unknownRuns = 0;
  const detailPromises = tasks.map(async (taskId) => {
    try {
      const r = await jget(`/api/semantic/ops_run_detail?task_id=${encodeURIComponent(taskId)}&limit=80`);
      const d = r?.data || {};
      const entries = Array.isArray(d.entries) ? d.entries : [];
      for (const e of entries) {
        if (String(e?.action || "") !== "finished") continue;
        const runAtMs = Number(e?.runAtMs || e?.ts || 0);
        if (!Number.isFinite(runAtMs) || runAtMs < floorMs) continue;
        const dur = Number(e?.durationMs || 0);
        if (Number.isFinite(dur) && dur > 0) allDurations.push(dur);
        const rq = normalizeRunQuality(parseRunQualityFromSummary(e?.summary), e?.status);
        if (rq === "ok_full") okFullRuns += 1;
        if (rq === "unknown") unknownRuns += 1;
        allRuns += 1;
      }
    } catch {
      // Ignore per-task detail errors to avoid breaking the dashboard.
    }
  });
  await Promise.all(detailPromises);
  allDurations.sort((a, b) => a - b);
  const p95 = allDurations.length
    ? allDurations[Math.min(allDurations.length - 1, Math.max(0, Math.round((allDurations.length - 1) * 0.95)))]
    : 0;
  const okFullRatio = allRuns > 0 ? okFullRuns / allRuns : 0;
  const unknownRatio = allRuns > 0 ? unknownRuns / allRuns : 0;
  return { p95, okFullRatio, unknownRatio, sampleRuns: allRuns };
}

async function loadOpsEvents() {
  const status = qs("opsStatus");
  const kpi = qs("opsKpiSummary");
  const activeSubview = currentOpsSubview();
  if (status) status.textContent = "加载中…";
  if (kpi) kpi.textContent = "";
  try {
    const r = await jget("/api/semantic/ops_events");
    const d = r.data || {};
    const healthRows = d.task_health_events || [];
    const healthIndex = buildHealthIndex(healthRows);
    renderRows("opsExecTbody", d.execution_audit_events || [], healthIndex);
    renderRows("opsCollectTbody", d.collection_quality_events || [], healthIndex);
    renderHealthRows("opsHealthTbody", healthRows);
    const q = (d._meta || {}).quality_status || "ok";
    const all = Array.isArray(healthRows) ? healthRows.length : 0;
    const bad = Array.isArray(healthRows)
      ? healthRows.filter((x) => String(x?.quality_status || "") === "degraded").length
      : 0;
    const okFull = Array.isArray(healthRows)
      ? healthRows.filter((x) => normalizeRunQuality(x?.run_quality, x?.last_run_status) === "ok_full").length
      : 0;
    const okDegraded = Array.isArray(healthRows)
      ? healthRows.filter((x) => normalizeRunQuality(x?.run_quality, x?.last_run_status) === "ok_degraded").length
      : 0;
    const error = Array.isArray(healthRows)
      ? healthRows.filter((x) => normalizeRunQuality(x?.run_quality, x?.last_run_status) === "error").length
      : 0;
    const unknown = Array.isArray(healthRows)
      ? healthRows.filter((x) => normalizeRunQuality(x?.run_quality, x?.last_run_status) === "unknown").length
      : 0;
    const p95 = calcDurationP95(healthRows);
    const onlyIssues = !!qs("opsOnlyIssues")?.checked;
    if (kpi) {
      kpi.textContent = `质量概览：ok_full=${okFull} | ok_degraded=${okDegraded} | error=${error} | unknown=${unknown} | P95=${p95 || 0}ms`;
    }
    // 仅在健康看板子页异步补充近3天基线对比，避免 exec/collect 刷新时高频拉详情。
    if (kpi && activeSubview === "health") {
      kpi.textContent += " | 近3天基线计算中...";
      loadBaseline3dMetrics(healthRows)
        .then((m) => {
          if (!kpi) return;
          const ratioPct = `${(Number(m.okFullRatio || 0) * 100).toFixed(1)}%`;
          const unknownPct = `${(Number(m.unknownRatio || 0) * 100).toFixed(1)}%`;
          const delta = Number(m.p95 || 0) > 0 ? Number(p95 || 0) - Number(m.p95 || 0) : 0;
          const deltaTxt = Number(m.p95 || 0) > 0 ? `${delta >= 0 ? "+" : ""}${delta}ms` : "n/a";
          kpi.textContent =
            `质量概览：ok_full=${okFull} | ok_degraded=${okDegraded} | error=${error} | unknown=${unknown} | P95=${p95 || 0}ms`
            + ` | 近3天基线：P95=${m.p95 || 0}ms(差值${deltaTxt}) ok_full占比=${ratioPct} unknown占比=${unknownPct} 样本=${m.sampleRuns || 0}`;
        })
        .catch(() => {
          if (!kpi) return;
          kpi.textContent += " | 近3天基线：读取失败";
        });
    }
    if (status) status.textContent = `已更新（语义层:${q}，任务总数:${all}，异常:${bad}，筛选:${onlyIssues ? "仅异常" : "全部"}）`;
  } catch (e) {
    if (status) status.textContent = String(e?.message || e);
  }
}

qs("tab-ops")?.addEventListener("click", () => {
  setView("ops");
  setOpsSubview("exec");
  loadOpsEvents();
});
qs("btnOpsRefresh")?.addEventListener("click", () => loadOpsEvents());
qs("subtab-ops-exec")?.addEventListener("click", () => setOpsSubview("exec"));
qs("subtab-ops-collect")?.addEventListener("click", () => setOpsSubview("collect"));
qs("subtab-ops-health")?.addEventListener("click", () => setOpsSubview("health"));
qs("opsOnlyIssues")?.addEventListener("change", () => loadOpsEvents());
wireOpsDetailModal();

