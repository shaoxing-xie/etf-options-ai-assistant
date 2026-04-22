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
  const isExec = name !== "collect";
  if (exec) exec.classList.toggle("active", isExec);
  if (collect) collect.classList.toggle("active", !isExec);
  const t1 = qs("subtab-ops-exec");
  const t2 = qs("subtab-ops-collect");
  if (t1) t1.setAttribute("aria-selected", String(isExec));
  if (t2) t2.setAttribute("aria-selected", String(!isExec));
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
    tr.innerHTML = `<td>${esc(r.task_id || "")}</td><td>${esc(r.name || "")}</td><td>${esc(r.schedule || "")}</td><td>${esc(
      r.last_run_status || "",
    )}</td><td${qStyle}>${esc(qLabel)}</td><td>${esc(r.consecutive_errors ?? "")}</td><td>${esc((r.tools_allow || []).join(","))}</td>`;
    tbody.appendChild(tr);
  }
}

async function loadOpsEvents() {
  const status = qs("opsStatus");
  if (status) status.textContent = "加载中…";
  try {
    const r = await jget("/api/semantic/ops_events");
    const d = r.data || {};
    renderRows("opsExecTbody", d.execution_audit_events || []);
    renderRows("opsCollectTbody", d.collection_quality_events || []);
    const q = (d._meta || {}).quality_status || "ok";
    if (status) status.textContent = `已更新（语义层:${q}）`;
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
qs("opsOnlyIssues")?.addEventListener("change", () => loadOpsEvents());

