// Organization dashboard: status banner, my opportunities, create/edit/close,
// signups + attendance marking, and stats. GET /api/me/organization, /me/opportunities,
// /me/organization/stats; POST/PATCH /api/opportunities; signups + attendance.
import L from "../leaflet-setup.js";
import { API, CATEGORIES, esc } from "../api.js";
import { icon } from "../icons.js";
import { categoryLabel, pinMarkup, inlineNotice } from "../ui.js";

let pickerMap = null;

function pinIcon(category) {
  return L.divIcon({
    className: "pin-wrap",
    html: pinMarkup("opp", category),
    iconSize: [44, 44],
    iconAnchor: [22, 22],
  });
}

const STATUS_LABEL = { open: "Open", closed: "Closed" };

export async function renderOrganization(app) {
  if (pickerMap) { pickerMap.remove(); pickerMap = null; }
  app.innerHTML = `<div class="page"><p class="empty" role="status" aria-live="polite">Loading…</p></div>`;
  const page = app.querySelector(".page");
  let org;
  try {
    org = await API.get("/me/organization");
  } catch (ex) {
    page.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`;
    return;
  }

  const banner =
    org.verification_status === "pending"
      ? `<div class="banner">${icon("clock", 16)}<span>Your organization is awaiting moderator approval. You can prepare offers, but they'll go live once approved.</span></div>`
      : org.verification_status === "rejected"
      ? `<div class="banner">${icon("ban", 16)}<span>Your organization was rejected.${org.comment ? ` Reason: ${esc(org.comment)}` : ""}</span></div>`
      : "";

  page.innerHTML = `
    <div class="page-head">
      ${icon("megaphone", 24)}
      <h1>${esc(org.org_name)}</h1>
      <span class="tag ${org.verification_status === "approved" ? "green" : org.verification_status === "pending" ? "amber" : "red"}">${esc(org.verification_status)}</span>
    </div>
    ${banner}
    <div id="orgErr" class="form-error" role="alert" hidden></div>
    <div id="statsBox"></div>
    <section class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
        <h2>Opportunities</h2>
        <button class="btn" id="newOppBtn">${icon("plus", 16)} New offer</button>
      </div>
      <div id="oppList"></div>
    </section>
    <section class="card" id="formCard" hidden></section>
  `;

  page.querySelector("#newOppBtn").onclick = () => showForm(page, null, org);
  loadStats(page);
  loadOpps(page, org);
}

async function loadStats(page) {
  const box = page.querySelector("#statsBox");
  try {
    const s = await API.get("/me/organization/stats");
    box.innerHTML = `
      <section class="card">
        <h2>Stats</h2>
        <div class="stats-grid">
          <div class="stat"><div class="stat-n">${s.opportunities_total}</div><div class="stat-l">Total offers</div></div>
          <div class="stat"><div class="stat-n">${s.opportunities_open}</div><div class="stat-l">Open</div></div>
          <div class="stat"><div class="stat-n">${s.signups_total}</div><div class="stat-l">Sign-ups</div></div>
          <div class="stat"><div class="stat-n">${s.attended_total}</div><div class="stat-l">Attended</div></div>
          <div class="stat"><div class="stat-n">${s.past_opportunities}</div><div class="stat-l">Past</div></div>
        </div>
      </section>`;
  } catch { box.innerHTML = ""; }
}


async function loadOpps(page, org) {
  const list = page.querySelector("#oppList");
  try {
    const opps = await API.get("/me/opportunities");
    if (!opps.length) {
      list.innerHTML = `<p class="empty">No offers yet.</p>`;
      return;
    }
    list.innerHTML = opps.map((o) => {
      const when = new Date(o.start_time).toLocaleString();
      const slots = `${o.slots_taken}/${o.slots_total} slots`;
      return `<div class="list-row">
        <div class="lr-main">
          <div class="lr-title">${esc(o.title)}</div>
          <div class="lr-sub">${esc(categoryLabel(o.category))} · ${esc(when)} · ${esc(slots)} · <span class="tag">${esc(STATUS_LABEL[o.status] || o.status)}</span>${o.is_hidden ? ` <span class="tag red">hidden</span>` : ""}</div>
        </div>
        <div class="lr-actions">
          <a class="btn secondary" href="#/opportunities/${o.id}">${icon("eye", 15)} View</a>
          <button class="btn secondary" data-edit="${o.id}">${icon("pencil", 15)} Edit</button>
          ${o.status === "open" ? `<button class="btn danger" data-close="${o.id}">Close</button>` : ""}
          <button class="btn secondary" data-signups="${o.id}">${icon("users", 15)} Sign-ups</button>
        </div>
      </div>`;
    }).join("");
    list.querySelectorAll("[data-edit]").forEach((b) => b.onclick = async () => {
      const o = await API.get(`/opportunities/${b.dataset.edit}`);
      showForm(page, o, org);
    });
    list.querySelectorAll("[data-close]").forEach((b) => b.onclick = async () => {
      try { await API.patch(`/opportunities/${b.dataset.close}/close`); loadOpps(page, org); loadStats(page); }
      catch (ex) { inlineNotice(page.querySelector("#orgErr"), ex.message); }
    });
    list.querySelectorAll("[data-signups]").forEach((b) => b.onclick = () => showSignups(page, b.dataset.signups));
  } catch (ex) {
    list.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`;
  }
}


function showForm(page, opp, org) {
  const card = page.querySelector("#formCard");
  card.hidden = false;
  const editing = !!opp;
  card.innerHTML = `
    <h2>${editing ? "Edit offer" : "New offer"}</h2>
    <form id="oppForm">
      <label for="f-title">Title</label>
      <input id="f-title" name="title" required maxlength="120" value="${opp ? esc(opp.title) : ""}" />
      <label for="f-cat">Category</label>
      <select id="f-cat" name="category"></select>
      <label for="f-desc">Description</label>
      <textarea id="f-desc" name="description" rows="3" maxlength="2000">${opp ? esc(opp.description || "") : ""}</textarea>
      <label for="f-slots">Slots</label>
      <input id="f-slots" name="slots_total" type="number" min="1" max="500" required value="${opp ? opp.slots_total : 10}" />
      <label for="f-start">Start time</label>
      <input id="f-start" name="start_time" type="datetime-local" required />
      <p class="field-hint">Pick a future date and time. Your local timezone is used.</p>
      <div class="compose-map" style="height:260px;margin-top:12px"><div id="pickerMap"></div></div>
      <div id="coords" class="field-hint">Click the map to place the pin.</div>
      <div id="ferr" class="form-error" role="alert" hidden></div>
      <div class="compose-actions" style="margin-top:16px">
        <button class="btn" type="submit">${editing ? "Save changes" : "Publish"}</button>
        <button class="btn secondary" type="button" id="fCancel">Cancel</button>
      </div>
    </form>`;
  const sel = card.querySelector("#f-cat");
  CATEGORIES.forEach((c) => {
    const o = document.createElement("option");
    o.value = c; o.textContent = categoryLabel(c);
    if (opp && opp.category === c) o.selected = true;
    sel.appendChild(o);
  });
  const startEl = card.querySelector("#f-start");
  const pad = (n) => String(n).padStart(2, "0");
  if (opp) {
    const d = new Date(opp.start_time);
    startEl.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } else {
    const d = new Date(Date.now() + 24 * 3600 * 1000);
    d.setHours(10, 0, 0, 0);
    startEl.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  pickerMap = L.map(card.querySelector("#pickerMap"), { zoomControl: false }).setView([50.4501, 30.5234], 13);
  L.control.zoom({ position: "bottomright" }).addTo(pickerMap);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap" }).addTo(pickerMap);
  requestAnimationFrame(() => pickerMap.invalidateSize());

  let marker = null;
  let picked = opp ? { lat: opp.latitude, lng: opp.longitude } : null;
  if (opp) {
    marker = L.marker([opp.latitude, opp.longitude], { icon: pinIcon(opp.category) }).addTo(pickerMap);
    card.querySelector("#coords").textContent = `${opp.latitude.toFixed(5)}, ${opp.longitude.toFixed(5)}`;
  }
  sel.addEventListener("change", () => { if (marker) marker.setIcon(pinIcon(sel.value)); });
  pickerMap.on("click", (e) => {
    picked = e.latlng;
    if (marker) marker.setLatLng(picked);
    else marker = L.marker(picked, { icon: pinIcon(sel.value) }).addTo(pickerMap);
    card.querySelector("#coords").textContent = `${picked.lat.toFixed(5)}, ${picked.lng.toFixed(5)}`;
  });

  card.querySelector("#fCancel").onclick = () => { card.hidden = true; if (pickerMap) { pickerMap.remove(); pickerMap = null; } };
  card.querySelector("#oppForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const err = card.querySelector("#ferr");
    err.hidden = true;
    if (!picked) { err.textContent = "Click the map to place the pin."; err.hidden = false; return; }
    const local = new Date(f.get("start_time"));
    if (isNaN(local) || local <= new Date()) { err.textContent = "Start time must be in the future."; err.hidden = false; return; }
    const body = {
      title: f.get("title"),
      category: f.get("category"),
      description: f.get("description") || null,
      slots_total: Number(f.get("slots_total")),
      latitude: picked.lat,
      longitude: picked.lng,
      start_time: local.toISOString(),
    };
    try {
      if (editing) await API.patch(`/opportunities/${opp.id}`, body);
      else await API.post("/opportunities", body);
      card.hidden = true; if (pickerMap) { pickerMap.remove(); pickerMap = null; }
      loadOpps(page, org); loadStats(page);
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  };
}

async function showSignups(page, oppId) {
  const card = page.querySelector("#formCard");
  card.hidden = false;
  card.innerHTML = `<h2>Sign-ups</h2><p class="empty" role="status" aria-live="polite">Loading…</p>`;
  try {
    const opp = await API.get(`/opportunities/${oppId}`);
    const started = new Date(opp.start_time) <= new Date();
    const rows = await API.get(`/opportunities/${oppId}/signups`);
    if (!rows.length) {
      card.innerHTML = `<h2>Sign-ups</h2><p class="empty">No sign-ups yet.</p><button class="btn secondary" id="ssBack">Back</button>`;
      card.querySelector("#ssBack").onclick = () => { card.hidden = true; };
      return;
    }
    card.innerHTML = `<h2>Sign-ups (${rows.length}/${opp.slots_total})</h2>
      ${started ? "" : `<p class="field-hint">Attendance can be marked only after the start time.</p>`}
      ${rows.map((s) => `<div class="list-row">
        <div class="photo-placeholder">${esc((s.volunteer.display_name || "?").charAt(0).toUpperCase())}</div>
        <div class="lr-main">
          <div class="lr-title">${esc(s.volunteer.display_name)}</div>
          <div class="lr-sub">Signed up ${new Date(s.signed_up_at).toLocaleString()}${s.attended === true ? " · attended" : s.attended === false ? " · absent" : ""}</div>
        </div>
        <div class="lr-actions">
          <button class="btn secondary" data-att="${s.id}" data-v="1" ${started ? "" : "disabled"}>Present</button>
          <button class="btn danger" data-att="${s.id}" data-v="0" ${started ? "" : "disabled"}>Absent</button>
        </div>
      </div>`).join("")}
      <button class="btn secondary" id="ssBack" style="margin-top:12px">Back</button>`;
    card.querySelectorAll("[data-att]").forEach((b) => b.onclick = async () => {
      try {
        await API.patch(`/opportunities/${oppId}/signups/${b.dataset.att}`, { attended: b.dataset.v === "1" });
        showSignups(page, oppId);
      } catch (ex) { inlineNotice(page.querySelector("#orgErr"), ex.message); }
    });
    card.querySelector("#ssBack").onclick = () => { card.hidden = true; };
  } catch (ex) {
    card.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`;
  }
}

