/** Renders L4 global_market_snapshot cards (红涨绿跌). */

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function direction(item) {
  const a = item?.change_abs;
  const p = item?.change_pct;
  if (typeof a === "number" && a !== 0) return a > 0 ? 1 : -1;
  if (typeof p === "number" && p !== 0) return p > 0 ? 1 : -1;
  return 0;
}

function fmtNum(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  if (Math.abs(n) >= 1000) return n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  return n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

function fmtChgAbs(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
}

function fmtPct(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function fmtBeijingTime(v) {
  if (!v) return "—";
  const d = new Date(String(v));
  if (Number.isNaN(d.getTime())) return String(v);
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
    .format(d)
    .replace(/\//g, "-");
}

function cardClass(item) {
  const d = direction(item);
  if (d > 0) return "gm-card quote-up";
  if (d < 0) return "gm-card quote-down";
  return "gm-card quote-flat";
}

function renderItemCard(item) {
  const sub = item?.subtitle ? `<div class="gm-sub">${esc(item.subtitle)}</div>` : "";
  const q = item?.quality_status ? `<span class="gm-meta">质量:${esc(item.quality_status)}</span>` : "";
  const semantics = item?.data_semantics ? `<span class="gm-meta">口径:${esc(item.data_semantics)}</span>` : "";
  const asOf = item?.as_of ? `<span class="gm-meta">时间:${esc(item.as_of)}</span>` : "";
  return `<div class="${cardClass(item)}" title="${esc(item.degraded_reason || "")}">
    <div class="gm-name">${esc(item.display_name || item.instrument_code || "")}</div>
    ${sub}
    <div class="gm-price">${fmtNum(item.last_price)}</div>
    <div class="gm-chg">${fmtChgAbs(item.change_abs)} ${fmtPct(item.change_pct)}</div>
    ${q}
    ${semantics}
    ${asOf}
  </div>`;
}

function fillGrid(el, items) {
  if (!el) return;
  const rows = Array.isArray(items) ? items : [];
  el.innerHTML = rows.map((x) => renderItemCard(x)).join("");
}

const DEFAULT_GM_GRIDS = {
  cn: "gmCnGrid",
  apac: "gmApacGrid",
  usEu: "gmUsEuGrid",
  fut: "gmFutGrid",
};

/**
 * @param {HTMLElement} root
 * @param {any} data
 * @param {{ grids?: Partial<typeof DEFAULT_GM_GRIDS>, statusId?: string }} [opts] — 投研子页传入专用 id，避免与「全球市场」Tab 重复
 */
export function renderGlobalMarketPage(root, data, opts) {
  if (!root || !data) return;
  const grids = { ...DEFAULT_GM_GRIDS, ...(opts && opts.grids ? opts.grids : {}) };
  const q = (id) => (id ? root.querySelector(`#${id}`) : null);
  const groups = Array.isArray(data.groups) ? data.groups : [];
  const cn = groups.find((g) => g.group_id === "cn_index");
  const gi = groups.find((g) => g.group_id === "global_index");
  const fut = groups.find((g) => g.group_id === "index_futures");
  fillGrid(q(grids.cn), cn?.items);
  const ap = gi?.subgroups?.find((s) => s.subgroup_id === "apac");
  const ue = gi?.subgroups?.find((s) => s.subgroup_id === "us_eu");
  fillGrid(q(grids.apac), ap?.items);
  fillGrid(q(grids.usEu), ue?.items);
  fillGrid(q(grids.fut), fut?.items);
  const statusSel = opts && opts.statusId ? `#${opts.statusId}` : "#globalMarketStatus";
  const st = root.querySelector(statusSel);
  if (st) {
    const allItems = [];
    const pushItems = (arr) => {
      if (Array.isArray(arr)) allItems.push(...arr);
    };
    pushItems(cn?.items);
    pushItems(ap?.items);
    pushItems(ue?.items);
    pushItems(fut?.items);
    const ages = allItems
      .map((x) => (typeof x?.freshness_age_sec === "number" ? x.freshness_age_sec : null))
      .filter((x) => typeof x === "number");
    const maxAge = ages.length ? Math.max(...ages) : null;
    const maxAgeText = maxAge === null ? "—" : `${Math.round(maxAge)}s`;
    const m = data._meta || {};
    const updateRaw = data.fetched_at || m.generated_at || "";
    st.textContent = `交易日 ${data.trade_date || m.trade_date || "—"} · 质量 ${m.quality_status || "—"} · 最老延迟 ${maxAgeText} · 更新(北京时间) ${fmtBeijingTime(updateRaw)}`;
  }
}

