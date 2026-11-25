// Opportunity detail page: #/opportunities/:id
// Volunteer: sign up / cancel. Owner: see signups + mark attendance.
import { API, esc, getUser } from "../api.js";
import { icon } from "../icons.js";
import { categoryLabel } from "../ui.js";

export async function renderOpportunity(app, id) {
  app.innerHTML = `<div class="page"><p class="empty">Loading…</p></div>`;
  const page = app.querySelector(".page");
  const user = getUser();
  try {
    const o = await API.get(`/opportunities/${id}`);
    const when = new Date(o.start_time).toLocaleString();
    const started = new Date(o.start_time) <= new Date();
    const full = o.slots_taken >= o.slots_total;
    let actions = "";
    if (o.is_owner) {
      actions = `<a class="btn secondary" href="#/organization">${icon("pencil", 15)} Manage</a>`;
    } else if (o.is_signed_up) {
      actions = `<button class="btn danger" id="cancelBtn" ${started ? "disabled" : ""}>Cancel sign-up</button>`;
    } else if (o.status !== "open") {
      actions = `<span class="quiet-line">This offer is closed.</span>`;
    } else if (full) {
      actions = `<span class="quiet-line">No free slots left.</span>`;
    } else if (started) {
      actions = `<span class="quiet-line">This offer has already started.</span>`;
    } else {
      actions = `<button class="btn" id="signupBtn">Sign up</button>`;
    }
    if (!o.is_owner) {
      actions += ` <button class="btn secondary" id="reportBtn">${icon("flag", 15)} Report</button>`;
    }
    page.innerHTML = `
      <div class="page-head"><a class="back" href="#/">${icon("chevron", 16)} Map</a></div>
      <section class="card">
        <div class="detail-kicker">${icon("megaphone", 15)} ${esc(o.organization.org_name)}</div>
        <h2 style="font-family:var(--display);font-weight:500;font-size:24px;margin:4px 0 8px">${esc(o.title)}</h2>
        <span class="tag ${o.status === "open" ? "green" : "red"}">${esc(o.status)}</span>
        ${o.is_hidden ? ` <span class="tag red">hidden</span>` : ""}
        ${o.description ? `<p class="detail-desc" style="margin:12px 0 0;white-space:pre-wrap">${esc(o.description)}</p>` : ""}
        <div class="detail-meta" style="margin-top:12px">
          <div class="meta-row">${icon("pin", 16)}<span>${Number(o.latitude).toFixed(5)}, ${Number(o.longitude).toFixed(5)}</span></div>
          <div class="meta-row">${icon("calendar", 16)}<span>${esc(when)}</span></div>
          <div class="meta-row">${icon("users", 16)}<span>${o.slots_taken}/${o.slots_total} signed up</span></div>
          <div class="meta-row">${icon("list", 16)}<span>${esc(categoryLabel(o.category))}</span></div>
        </div>
        <div id="oErr" class="form-error" hidden></div>
        <div class="actions" style="margin-top:14px">${actions}</div>
      </section>`;
    const signupBtn = page.querySelector("#signupBtn");
    if (signupBtn) signupBtn.onclick = async () => {
      signupBtn.disabled = true;
      try { await API.post(`/opportunities/${id}/signups`); renderOpportunity(app, id); }
      catch (ex) { const e = page.querySelector("#oErr"); e.hidden = false; e.textContent = ex.message; signupBtn.disabled = false; }
    };
    const cancelBtn = page.querySelector("#cancelBtn");
    if (cancelBtn) cancelBtn.onclick = async () => {
      cancelBtn.disabled = true;
      try { await API.del(`/opportunities/${id}/signups/me`); renderOpportunity(app, id); }
      catch (ex) { const e = page.querySelector("#oErr"); e.hidden = false; e.textContent = ex.message; cancelBtn.disabled = false; }
    };
    const reportBtn = page.querySelector("#reportBtn");
    if (reportBtn) reportBtn.onclick = async () => {
      const reason = window.prompt("Why are you reporting this offer? (3–500 characters)");
      if (!reason || !reason.trim()) return;
      const err = page.querySelector("#oErr");
      try {
        await API.post("/reports", { target_type: "opportunity", target_id: Number(id), reason: reason.trim() });
        if (err) { err.hidden = false; err.textContent = "Reported. Thank you."; }
      } catch (ex) {
        if (err) { err.hidden = false; err.textContent = ex.message; }
      }
    };
  } catch (ex) {
    page.innerHTML = `<div class="form-error">${esc(ex.message)}</div>`;
  }
}
