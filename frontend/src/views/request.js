// Standalone request detail page: #/requests/:id
// Reuses the same lifecycle as the map detail panel but as a full page so a
// refresh on #/requests/5 survives (the backend serves index.html for unknown paths).
import { API, esc, getUser, loadPhoto } from "../api.js";
import { icon } from "../icons.js";
import { CATEGORY_ICON, categoryLabel, statusLabel, pinCat } from "../ui.js";

const STATUS_CLASS = new Set(["open", "claimed", "completed", "confirmed", "cancelled"]);

export async function renderRequest(app, id) {
  app.innerHTML = `<div class="page"><p class="empty">Loading…</p></div>`;
  const user = getUser();
  const page = app.querySelector(".page");
  try {
    const r = await API.get(`/requests/${id}`);
    const rid = Number(r.id);
    const b = (action, label, cls = "", claimId = null) =>
      `<button type="button" class="btn ${cls}" data-id="${rid}" data-act="${action}"${claimId == null ? "" : ` data-claim="${Number(claimId)}"`}>${label}</button>`;
    const buttons = [];
    if (user.roles.includes("volunteer") && r.status === "open" && !r.is_mine) {
      buttons.push(b("claim", "Claim"));
    }
    if (r.is_mine && r.status === "claimed" && !r.accepted && r.claimer?.claim_id != null) {
      buttons.push(b("accept", "Accept", "", r.claimer.claim_id), b("decline", "Decline", "secondary", r.claimer.claim_id));
    }
    if (r.is_claimer && r.status === "claimed" && r.accepted) {
      buttons.push(b("complete", "Mark completed"));
    }
    if (r.is_claimer && r.status === "claimed") {
      buttons.push(b("release", "Release", "secondary"));
    }
    if (r.is_mine && (r.status === "open" || r.status === "claimed")) {
      buttons.push(b("cancel", "Cancel request", "danger"));
    }
    if (r.is_mine && r.status === "completed") {
      buttons.push(b("confirm", "Confirm received"), b("reopen", "Not resolved", "secondary"));
    }
    if (!r.is_mine) {
      buttons.push(b("report", `${icon("flag", 15)} Report`, "secondary"));
    }

    const statusClass = STATUS_CLASS.has(r.status) ? r.status : "open";
    const where = r.exact_location
      ? `${Number(r.latitude).toFixed(5)}, ${Number(r.longitude).toFixed(5)}`
      : "Approximate";
    const addr = r.exact_location && r.address
      ? `<div class="meta-row">${icon("house", 16)}<span>${esc(r.address)}</span></div>`
      : "";
    const claimer = r.claimer && r.is_mine
      ? `<div class="meta-row">${icon("user", 16)}<span>Claimed by <b>${esc(r.claimer.display_name)}</b>${r.claimer.is_verified ? ` ${icon("badgeCheck", 14)}` : ""}, helped ${Number(r.claimer.confirmed_count) || 0} times before</span></div>`
      : "";
    const hidden = r.is_hidden && r.is_mine
      ? `<div class="callout">${icon("alert", 16)}<span>This request was hidden by a moderator or by 3 reports. It's still visible to you.</span></div>`
      : "";
    const photoHolder = (r.claimer && r.is_mine && r.claimer.photo_url) || (r.is_claimer && r.author_photo_url)
      ? `<img id="partyPhoto" alt="" class="photo-thumb" style="margin-top:12px" />`
      : "";
    const when = r.created_at ? new Date(r.created_at).toLocaleString() : "";

    page.innerHTML = `
      <div class="page-head">
        <a class="back" href="#/">${icon("chevron", 16)} Map</a>
      </div>
      <section class="card">
        <div class="detail-kicker cat-${pinCat(r.category)}">${icon(CATEGORY_ICON[r.category] || "ellipsis", 15)} ${esc(categoryLabel(r.category))}</div>
        <h2 style="font-family:var(--display);font-weight:500;font-size:24px;margin:4px 0 8px">${esc(r.title || categoryLabel(r.category))}</h2>
        <span class="status ${statusClass}"><i></i>${esc(statusLabel(r.status))}</span>
        <p class="detail-desc" style="margin:12px 0 0;white-space:pre-wrap">${esc(r.description)}</p>
        <div class="detail-meta">
          <div class="meta-row">${icon("pin", 16)}<span>${esc(where)}</span></div>
          ${addr}
          ${claimer}
          <div class="meta-row">${icon("clock", 16)}<span>${esc(when)}</span></div>
        </div>
        ${photoHolder}
        ${hidden}
        <div id="detailError" class="form-error" hidden></div>
        <div class="actions">${buttons.join("") || '<span class="quiet-line">Nothing for you to do on this one.</span>'}</div>
      </section>
    `;

    const photoPath = (r.claimer && r.is_mine && r.claimer.photo_url) || (r.is_claimer && r.author_photo_url);
    if (photoPath) {
      const img = page.querySelector("#partyPhoto");
      if (img) {
        loadPhoto(photoPath).then((url) => { if (url) img.src = url; else img.remove(); });
      }
    }

    page.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-act]");
      if (btn) act(btn, id);
    });
  } catch (ex) {
    page.innerHTML = `<div class="form-error">${esc(ex.message)}</div>`;
  }
}

async function act(btn, id) {
  const { act: action, claim } = btn.dataset;
  if (action === "report") {
    const reason = window.prompt("Why are you reporting this request? (3–500 characters)");
    if (!reason || !reason.trim()) return;
    const err = document.getElementById("detailError");
    try {
      await API.post("/reports", { target_type: "request", target_id: Number(id), reason: reason.trim() });
      if (err) { err.hidden = false; err.textContent = "Reported. Thank you."; }
    } catch (ex) {
      if (err) { err.hidden = false; err.textContent = ex.message; }
    }
    return;
  }
  if (action === "cancel" && !btn.dataset.sure) {
    btn.dataset.sure = "1";
    btn.textContent = "Confirm cancel";
    return;
  }
  document.querySelectorAll(".page .btn").forEach((b) => (b.disabled = true));
  try {
    await API.patch(`/requests/${id}/${action}`, claim ? { claim_id: Number(claim) } : undefined);
    if (action === "cancel" || action === "confirm") {
      location.hash = "#/";
    } else {
      renderRequest(document.getElementById("app"), id);
    }
  } catch (ex) {
    const err = document.getElementById("detailError");
    if (err) { err.hidden = false; err.textContent = ex.message; }
    document.querySelectorAll(".page .btn").forEach((b) => (b.disabled = false));
  }
}
