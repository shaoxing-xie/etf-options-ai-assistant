import { jget } from "./api.js";
import { setView } from "./app.js";

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

function renderRows(tbodyId, rows) {
  const tbody = qs(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = "";
  const onlyIssues = !!qs("opsOnlyIssues")?.checked;
  const src = Array.isArray(rows) ? rows : [];
  const list = onlyIssues
    ? src.filter((r) => {
        const q = String(r?.quality_status || "");
        const s = String(r?.last_run_status || "");
        return q === "degraded" || s === "error" || Number(r?.consecutive_errors || 0) > 0;
      })
    : src;
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td colspan='7'>暂无事件</td>";
    tbody.appendChild(tr);
    return;
  }
  for (const r of list) {
    const tr = document.createElement("tr");
    const q = String(r.quality_status || "");
    const qLabel = q || "ok";
    const qStyle = qLabel === "degraded" ? " style='color:#f7c88a;font-weight:600;'" : "";
    const status = String(r.status || r.last_run_status || "");
    const statusStyle = status === "error" ? " style='color:#ff9a9a;font-weight:600;'" : "";
    const nameAddon = r.audit_domain === "nikkei225_etf_monitor"
      ? ` <span class="chip">nikkei审计:${esc(r.monitor_group || "")}</span>`
      : (r.audit_domain === "nasdaq100_etf_monitor"
          ? ` <span class="chip">nasdaq审计:${esc(r.monitor_group || "")}</span>`
          : "");
    tr.innerHTML = `<td>${esc(r.task_id || "")}</td><td>${esc(r.name || "")}${nameAddon}</td><td>${esc(r.schedule || "")}</td><td${statusStyle}>${esc(
      status,
    )}</td><td${qStyle}>${esc(qLabel)}</td><td>${esc(r.consecutive_errors ?? "")}</td><td>${esc((r.tools_allow || []).join(","))}</td>`;
    tbody.appendChild(tr);
  }
}

function renderHealthRows(tbodyId, rows) {
  const tbody = qs(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = "";
  const onlyIssues = !!qs("opsOnlyIssues")?.checked;
  const src = Array.isArray(rows) ? rows : [];
  const base = onlyIssues ? src.filter((r) => String(r?.quality_status || "") === "degraded") : src;
  const list = [...base].sort((a, b) => String(a?.task_id || "").localeCompare(String(b?.task_id || "")));
  if (!list.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td colspan='9'>暂无事件</td>";
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
    const q = String(r.quality_status || "");
    const qLabel = q || "ok";
    const qStyle = qLabel === "degraded" ? " style='color:#f7c88a;font-weight:600;'" : "";
    const err = String(r.error || "").trim();
    const errShort = err.length > 140 ? `${err.slice(0, 140)}...` : err;
    tr.innerHTML = `<td>${esc(r.task_id || "")}</td><td>${esc(r.name || "")}</td><td>${esc(r.schedule || "")}</td><td>${esc(
      r.last_run_status || "",
    )}</td><td${qStyle}>${esc(qLabel)}</td><td>${esc(r.consecutive_errors ?? "")}</td><td>${esc(errShort)}</td><td>${esc(
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

async function loadOpsEvents() {
  const status = qs("opsStatus");
  if (status) status.textContent = "加载中…";
  try {
    const r = await jget("/api/semantic/ops_events");
    const d = r.data || {};
    renderRows("opsExecTbody", d.execution_audit_events || []);
    renderRows("opsCollectTbody", d.collection_quality_events || []);
    renderHealthRows("opsHealthTbody", d.task_health_events || []);
    const q = (d._meta || {}).quality_status || "ok";
    const all = Array.isArray(d.task_health_events) ? d.task_health_events.length : 0;
    const bad = Array.isArray(d.task_health_events)
      ? d.task_health_events.filter((x) => String(x?.quality_status || "") === "degraded").length
      : 0;
    const onlyIssues = !!qs("opsOnlyIssues")?.checked;
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

