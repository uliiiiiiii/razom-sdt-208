// Moderator dashboard: #/moderation
// Tabs: reports queue (with logged address view), report decisions,
// hide/unhide, organization approvals, user search/block, access log,
// stats, and identity-verification review (image viewing logged).
import { API, esc, loadPhoto } from "../api.js";
import { icon } from "../icons.js";

let tab = "reports";
let reportStatus = "open";

export async function renderModeration(app) {
  app.innerHTML = `<div class="page"><p class="empty" role="status" aria-live="polite">Loading…</p></div>`;
  draw(app);
}

async function draw(app) {
  const page = app.querySelector(".page");
  page.innerHTML = `
    <div class="page-head">${icon("shieldCheck", 24)}<h1>Moderation</h1></div>
    <div class="tabs" role="tablist" id="modTabs">
      <button class="tab ${tab === "reports" ? "on" : ""}" role="tab" aria-selected="${tab === "reports"}" data-t="reports">${icon("flag", 14)} Reports</button>
      <button class="tab ${tab === "orgs" ? "on" : ""}" role="tab" aria-selected="${tab === "orgs"}" data-t="orgs">${icon("building", 14)} Organizations</button>
      <button class="tab ${tab === "users" ? "on" : ""}" role="tab" aria-selected="${tab === "users"}" data-t="users">${icon("users", 14)} Users</button>
      <button class="tab ${tab === "verify" ? "on" : ""}" role="tab" aria-selected="${tab === "verify"}" data-t="verify">${icon("badgeCheck", 14)} Verifications</button>
      <button class="tab ${tab === "log" ? "on" : ""}" role="tab" aria-selected="${tab === "log"}" data-t="log">${icon("eye", 14)} Access log</button>
      <button class="tab ${tab === "stats" ? "on" : ""}" role="tab" aria-selected="${tab === "stats"}" data-t="stats">${icon("chart", 14)} Stats</button>
    </div>
    <div id="modBody" role="tabpanel"></div>`;
  page.querySelector("#modTabs").addEventListener("click", (e) => {
    const b = e.target.closest(".tab");
    if (!b) return;
    tab = b.dataset.t;
    draw(app);
  });
  const body = page.querySelector("#modBody");
  if (tab === "reports") await reportsTab(body, app);
  else if (tab === "orgs") await orgsTab(body);
  else if (tab === "users") await usersTab(body);
  else if (tab === "verify") await verifyTab(body, app);
  else if (tab === "log") await logTab(body);
  else if (tab === "stats") await statsTab(body);
}

async function reportsTab(body, app) {
  let before = null;
  const LIMIT = 50;
  body.innerHTML = `
    <div class="tabs" role="tablist" id="repStatusTabs">
      <button class="tab ${reportStatus === "open" ? "on" : ""}" role="tab" aria-selected="${reportStatus === "open"}" data-s="open">Open</button>
      <button class="tab ${reportStatus === "dismissed" ? "on" : ""}" role="tab" aria-selected="${reportStatus === "dismissed"}" data-s="dismissed">Dismissed</button>
      <button class="tab ${reportStatus === "actioned" ? "on" : ""}" role="tab" aria-selected="${reportStatus === "actioned"}" data-s="actioned">Actioned</button>
    </div>
    <div id="repList"></div>
    <button class="btn secondary btn-block load-more" id="repMore" hidden>Load older</button>`;
  body.querySelector("#repStatusTabs").addEventListener("click", (e) => {
    const b = e.target.closest(".tab");
    if (!b) return;
    reportStatus = b.dataset.s;
    before = null;
    reportsTab(body, app);
  });
  const list = body.querySelector("#repList");
  const moreBtn = body.querySelector("#repMore");
  async function load() {
    let url = `/moderation/reports?status=${reportStatus}&limit=${LIMIT}`;
    if (before) url += `&before=${before}`;
    try {
      const rows = await API.get(url);
      if (!before && !rows.length) { list.innerHTML = `<p class="empty">No ${reportStatus} reports.</p>`; moreBtn.hidden = true; return; }
      list.insertAdjacentHTML("beforeend", rows.map((r) => `
        <div class="list-row">
          <div class="lr-main">
            <div class="lr-title">${esc(r.target_type)} #${r.target_id} · <span class="tag">${esc(r.status)}</span> · ${r.open_reports_on_target} open</div>
            <div class="lr-sub">${esc(r.reason)} — by ${esc(r.reporter.display_name)}, ${new Date(r.created_at).toLocaleString()}</div>
          </div>
          <div class="lr-actions">
            <button class="btn secondary" data-rep="${r.id}">${icon("eye", 15)} Review</button>
          </div>
        </div>`).join(""));
      moreBtn.hidden = rows.length < LIMIT;
      if (rows.length) before = rows[rows.length - 1].id;
      list.querySelectorAll("[data-rep]").forEach((b) => b.onclick = () => reviewReport(body, b.dataset.rep, app));
    } catch (ex) { list.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`; }
  }
  moreBtn.onclick = load;
  load();
}

async function reviewReport(body, reportId, app) {
  body.innerHTML = `<p class="empty" role="status" aria-live="polite">Loading…</p>`;
  try {
    const r = await API.get(`/moderation/reports/${reportId}`);
    let targetHtml = "<p class=\"empty\">Target no longer exists.</p>";
    const t = r.target;
    if (t) {
      if (r.target_type === "request") {
        targetHtml = `<dl class="dl-list">
          <dt>Title</dt><dd>${esc(t.title || "(none)")}</dd>
          <dt>Category</dt><dd>${esc(t.category)}</dd>
          <dt>Description</dt><dd>${esc(t.description)}</dd>
          <dt>Status</dt><dd>${esc(t.status)}</dd>
          <dt>Address</dt><dd>${t.address ? esc(t.address) : "(approximate / not revealed)"}</dd>
        </dl>`;
      } else if (r.target_type === "opportunity") {
        targetHtml = `<dl class="dl-list">
          <dt>Title</dt><dd>${esc(t.title)}</dd>
          <dt>Org</dt><dd>${esc(t.organization?.org_name || "")}</dd>
          <dt>Category</dt><dd>${esc(t.category)}</dd>
          <dt>Status</dt><dd>${esc(t.status)}</dd>
        </dl>`;
      } else {
        targetHtml = `<dl class="dl-list">
          <dt>Name</dt><dd>${esc(t.display_name)}</dd>
          <dt>Roles</dt><dd>${esc((t.roles || []).join(", "))}</dd>
          <dt>Blocked</dt><dd>${t.is_blocked ? "yes" : "no"}</dd>
        </dl>`;
      }
    }
    const logged = r.target_type === "request" && t?.address
      ? `<div class="banner">${icon("alert", 16)}<span>Viewing the exact address of a request with an open report is logged.</span></div>` : "";
    body.innerHTML = `
      <section class="card">
        <a class="back" href="#/moderation" id="repBack">${icon("chevron", 16)} Back to reports</a>
        <h2>Report #${r.id}</h2>
        <dl class="dl-list">
          <dt>Target</dt><dd>${esc(r.target_type)} #${r.target_id}</dd>
          <dt>Reason</dt><dd>${esc(r.reason)}</dd>
          <dt>Reporter</dt><dd>${esc(r.reporter.display_name)}</dd>
          <dt>Status</dt><dd>${esc(r.status)}</dd>
          <dt>Open on target</dt><dd>${r.open_reports_on_target}</dd>
        </dl>
        <h2 style="margin-top:16px">Reported content</h2>
        ${targetHtml}
        ${logged}
        ${r.status === "open" ? `
          <div class="actions" style="margin-top:14px">
            <button class="btn" data-d="dismiss">Dismiss</button>
            <button class="btn secondary" data-d="hide">Hide content</button>
            <button class="btn danger" data-d="block">Block user</button>
          </div>` : `<p class="field-hint">This report was already resolved.</p>`}
        <div id="repErr" class="form-error" role="alert" hidden></div>
      </section>`;
    body.querySelector("#repBack").onclick = () => { tab = "reports"; draw(app); };
    body.querySelectorAll("[data-d]").forEach((b) => b.onclick = async () => {
      const err = body.querySelector("#repErr");
      err.hidden = true;
      try { await API.patch(`/moderation/reports/${reportId}`, { decision: b.dataset.d }); tab = "reports"; draw(app); }
      catch (ex) { err.textContent = ex.message; err.hidden = false; }
    });
  } catch (ex) {
    body.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`;
  }
}

async function orgsTab(body) {
  let status = "pending";
  body.innerHTML = `
    <div class="tabs" role="tablist" id="orgStatusTabs">
      <button class="tab on" role="tab" aria-selected="true" data-s="pending">Pending</button>
      <button class="tab" role="tab" aria-selected="false" data-s="approved">Approved</button>
      <button class="tab" role="tab" aria-selected="false" data-s="rejected">Rejected</button>
    </div>
    <div id="orgList"></div>`;
  body.querySelector("#orgStatusTabs").addEventListener("click", (e) => {
    const b = e.target.closest(".tab");
    if (!b) return;
    status = b.dataset.s;
    body.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("on", t === b);
      t.setAttribute("aria-selected", t === b ? "true" : "false");
    });
    load();
  });
  const list = body.querySelector("#orgList");
  async function load() {
    list.innerHTML = `<p class="empty" role="status" aria-live="polite">Loading…</p>`;
    try {
      const rows = await API.get(`/moderation/organizations?status=${status}`);
      if (!rows.length) { list.innerHTML = `<p class="empty">No ${status} organizations.</p>`; return; }
      list.innerHTML = rows.map((o) => `
        <div class="list-row">
          <div class="lr-main">
            <div class="lr-title">${esc(o.org_name)}</div>
            <div class="lr-sub">${esc(o.user.email)} · ${esc(o.user.display_name)} · ${esc(o.verification_status)} · ${new Date(o.created_at).toLocaleDateString()}</div>
          </div>
          <div class="lr-actions">
            ${status === "pending" ? `
              <button class="btn" data-approve="${o.id}">Approve</button>
              <button class="btn danger" data-reject="${o.id}">Reject</button>` : ""}
            <button class="btn secondary" data-stats="${o.id}">${icon("chart", 15)} Stats</button>
          </div>
        </div>`).join("");
      list.querySelectorAll("[data-approve]").forEach((b) => b.onclick = async () => {
        try { await API.patch(`/moderation/organizations/${b.dataset.approve}`, { decision: "approved" }); load(); }
        catch (ex) { alert(ex.message); }
      });
      list.querySelectorAll("[data-reject]").forEach((b) => b.onclick = async () => {
        const comment = window.prompt("Reason for rejection (optional):") || "";
        try { await API.patch(`/moderation/organizations/${b.dataset.reject}`, { decision: "rejected", comment }); load(); }
        catch (ex) { alert(ex.message); }
      });
      list.querySelectorAll("[data-stats]").forEach((b) => b.onclick = async () => {
        try {
          const s = await API.get(`/moderation/organizations/${b.dataset.stats}/stats`);
          alert(`${s.opportunities_total} offers, ${s.signups_total} sign-ups, ${s.attended_total} attended, ${s.past_opportunities} past.`);
        } catch (ex) { alert(ex.message); }
      });
    } catch (ex) { list.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`; }
  }
  load();
}


async function usersTab(body) {
  let before = null;
  const LIMIT = 50;
  body.innerHTML = `
    <label for="userSearch" class="sr-only">Search users by email or name</label>
    <input id="userSearch" type="search" placeholder="Search by email or name…" />
    <div id="userList"></div>
    <button class="btn secondary btn-block load-more" id="userMore" hidden>Load older</button>`;
  const searchEl = body.querySelector("#userSearch");
  const list = body.querySelector("#userList");
  const moreBtn = body.querySelector("#userMore");
  let q = "";
  let searchTimer = null;
  searchEl.oninput = () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { q = searchEl.value.trim(); before = null; list.innerHTML = ""; load(); }, 300);
  };
  async function load() {
    let url = `/moderation/users?limit=${LIMIT}`;
    if (q) url += `&q=${encodeURIComponent(q)}`;
    if (before) url += `&before=${before}`;
    try {
      const rows = await API.get(url);
      if (!before && !rows.length) { list.innerHTML = `<p class="empty">No users found.</p>`; moreBtn.hidden = true; return; }
      list.insertAdjacentHTML("beforeend", rows.map((u) => `
        <div class="list-row">
          <div class="photo-placeholder">${esc((u.display_name || "?").charAt(0).toUpperCase())}</div>
          <div class="lr-main">
            <div class="lr-title">${esc(u.display_name)} ${u.is_verified ? icon("badgeCheck", 14) : ""} ${u.is_blocked ? '<span class="tag red">blocked</span>' : ""} ${u.is_moderator ? '<span class="tag">mod</span>' : ""}</div>
            <div class="lr-sub">${esc(u.email)} · ${(u.roles || []).join(", ")} · joined ${new Date(u.created_at).toLocaleDateString()}</div>
          </div>
          <div class="lr-actions">
            ${u.is_blocked ? `<button class="btn secondary" data-unblock="${u.id}">Unblock</button>` : `<button class="btn danger" data-block="${u.id}">Block</button>`}
            ${u.is_verified ? `<button class="btn danger" data-revoke="${u.id}">Revoke badge</button>` : ""}
          </div>
        </div>`).join(""));
      moreBtn.hidden = rows.length < LIMIT;
      if (rows.length) before = rows[rows.length - 1].id;
      list.querySelectorAll("[data-block]").forEach((b) => b.onclick = async () => {
        if (!confirm("Block this user? Their claims are released and badge revoked.")) return;
        try { await API.patch(`/moderation/users/${b.dataset.block}`, { is_blocked: true }); before = null; list.innerHTML = ""; load(); }
        catch (ex) { alert(ex.message); }
      });
      list.querySelectorAll("[data-unblock]").forEach((b) => b.onclick = async () => {
        try { await API.patch(`/moderation/users/${b.dataset.unblock}`, { is_blocked: false }); before = null; list.innerHTML = ""; load(); }
        catch (ex) { alert(ex.message); }
      });
      list.querySelectorAll("[data-revoke]").forEach((b) => b.onclick = async () => {
        const comment = window.prompt("Reason for revoking the badge (shown to the user):") || "";
        try { await API.patch(`/moderation/users/${b.dataset.revoke}`, { is_verified: false, verification_comment: comment }); before = null; list.innerHTML = ""; load(); }
        catch (ex) { alert(ex.message); }
      });
    } catch (ex) { list.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`; }
  }
  moreBtn.onclick = load;
  load();

async function verifyTab(body, app) {
  body.innerHTML = `<div id="verifyList"></div>`;
  const list = body.querySelector("#verifyList");
  try {
    const rows = await API.get("/moderation/verifications");
    if (!rows.length) { list.innerHTML = `<p class="empty">No pending verifications.</p>`; return; }
    list.innerHTML = rows.map((r) => `
      <div class="list-row">
        <div class="photo-placeholder">${esc((r.user.display_name || "?").charAt(0).toUpperCase())}</div>
        <div class="lr-main">
          <div class="lr-title">${esc(r.user.display_name)}</div>
          <div class="lr-sub">${esc((r.user.roles || []).join(", "))} · submitted ${r.submitted_at ? new Date(r.submitted_at).toLocaleString() : "?"}${r.duplicates?.length ? ` · ${r.duplicates.length} duplicate(s)` : ""}</div>
        </div>
        <div class="lr-actions">
          <button class="btn secondary" data-vr="${r.id}">${icon("eye", 15)} Review</button>
        </div>
      </div>`).join("");
    list.querySelectorAll("[data-vr]").forEach((b) => b.onclick = () => reviewVerification(body, b.dataset.vr, app));
  } catch (ex) { list.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`; }
}

}

async function reviewVerification(body, vid, app) {
  body.innerHTML = `<p class="empty" role="status" aria-live="polite">Loading…</p>`;
  try {
    const r = await API.get(`/moderation/verifications/${vid}`);
    const kinds = r.images || [];
    const dupes = r.duplicates || [];
    body.innerHTML = `
      <section class="card">
        <a class="back" href="#/moderation" id="vBack">${icon("chevron", 16)} Back</a>
        <h2>${esc(r.user.display_name)}</h2>
        <p class="card-sub">${esc((r.user.roles || []).join(", "))} · submitted ${r.submitted_at ? new Date(r.submitted_at).toLocaleString() : "?"}</p>
        ${dupes.length ? `<div class="banner" style="margin-top:12px">${icon("alert", 16)}<span>Possible duplicates: ${dupes.map((d) => esc(d.display_name)).join(", ")}</span></div>` : ""}
        <div class="banner" style="margin-top:12px">${icon("alert", 16)}<span>Every image you open is logged.</span></div>
        <div class="img-grid" id="imgGrid">
          ${kinds.map((k) => `<div class="img-card"><img alt="" data-kind="${k}" /><div class="img-label">${esc(k)}</div></div>`).join("")}
        </div>
        <div class="actions" style="margin-top:14px">
          <button class="btn" data-dec="approved">Approve</button>
          <button class="btn danger" data-dec="rejected">Reject</button>
        </div>
        <div id="vErr" class="form-error" role="alert" hidden></div>
      </section>`;
    body.querySelector("#vBack").onclick = () => { tab = "verify"; draw(app); };
    const photos = [];
    body.querySelectorAll("[data-kind]").forEach(async (img) => {
      const k = img.dataset.kind;
      const p = loadPhoto(`/moderation/verifications/${vid}/images/${k}`);
      photos.push(p);
      p.then((url) => { if (url) img.src = url; });
    });
    body.querySelectorAll("[data-dec]").forEach((b) => b.onclick = async () => {
      const err = body.querySelector("#vErr");
      err.hidden = true;
      const decision = b.dataset.dec;
      let comment = null;
      if (decision === "rejected") {
        comment = window.prompt("Reason for rejection (required):");
        if (!comment || !comment.trim()) { err.textContent = "A comment is required when rejecting."; err.hidden = false; return; }
      }
      try { await API.patch(`/moderation/verifications/${vid}`, { decision, comment }); photos.forEach((p) => p.revoke()); tab = "verify"; draw(app); }
      catch (ex) { err.textContent = ex.message; err.hidden = false; }
    });
  } catch (ex) {
    body.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`;
  }
}

async function logTab(body) {
  let before = null;
  const LIMIT = 50;
  body.innerHTML = `
    <label for="logReqId">Filter by request ID (optional)</label>
    <input id="logReqId" type="number" placeholder="Request ID" />
    <div id="logList"></div>
    <button class="btn secondary btn-block load-more" id="logMore" hidden>Load older</button>`;
  const reqEl = body.querySelector("#logReqId");
  const list = body.querySelector("#logList");
  const moreBtn = body.querySelector("#logMore");
  let reqId = null;
  let timer = null;
  reqEl.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(() => { reqId = reqEl.value ? Number(reqEl.value) : null; before = null; list.innerHTML = ""; load(); }, 300);
  };
  async function load() {
    let url = `/moderation/access-log?limit=${LIMIT}`;
    if (reqId) url += `&request_id=${reqId}`;
    if (before) url += `&before=${before}`;
    try {
      const rows = await API.get(url);
      if (!before && !rows.length) { list.innerHTML = `<p class="empty">No access log entries.</p>`; moreBtn.hidden = true; return; }
      list.insertAdjacentHTML("beforeend", rows.map((a) => `
        <div class="list-row">
          <div class="lr-main">
            <div class="lr-title">${esc(a.user.display_name)} viewed request #${a.request_id}</div>
            <div class="lr-sub">via ${esc(a.via)} · ${new Date(a.accessed_at).toLocaleString()}</div>
          </div>
        </div>`).join(""));
      moreBtn.hidden = rows.length < LIMIT;
      if (rows.length) before = rows[rows.length - 1].id;
    } catch (ex) { list.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`; }
  }
  moreBtn.onclick = load;
  load();
}

async function statsTab(body) {
  body.innerHTML = `<p class="empty" role="status" aria-live="polite">Loading…</p>`;
  try {
    const s = await API.get("/moderation/stats");
    body.innerHTML = `
      <section class="card">
        <h2>Platform</h2>
        <div class="stats-grid">
          <div class="stat"><div class="stat-n">${s.users_total}</div><div class="stat-l">Users</div></div>
          <div class="stat"><div class="stat-n">${s.active_users_30d}</div><div class="stat-l">Active (30d)</div></div>
          <div class="stat"><div class="stat-n">${s.pending_reports}</div><div class="stat-l">Pending reports</div></div>
          <div class="stat"><div class="stat-n">${s.pending_organizations}</div><div class="stat-l">Pending orgs</div></div>
        </div>
        <h2 style="margin-top:16px">Requests by status</h2>
        <div class="stats-grid">
          ${Object.entries(s.requests_by_status || {}).map(([k, v]) => `<div class="stat"><div class="stat-n">${v}</div><div class="stat-l">${esc(k)}</div></div>`).join("") || '<p class="empty">None</p>'}
        </div>
        <h2 style="margin-top:16px">Requests by category</h2>
        <div class="stats-grid">
          ${Object.entries(s.requests_by_category || {}).map(([k, v]) => `<div class="stat"><div class="stat-n">${v}</div><div class="stat-l">${esc(k)}</div></div>`).join("") || '<p class="empty">None</p>'}
        </div>
      </section>`;
  } catch (ex) { body.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`; }
}


