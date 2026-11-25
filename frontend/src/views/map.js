// Map screen: radius search over requests + opportunities (GET /api/map).
// Click a request marker to open the detail panel and its lifecycle:
// claim -> resident accept/decline -> complete -> confirm/reopen -> cancel.
import L from "../leaflet-setup.js";
import { API, esc, getUser, CATEGORIES, loadPhoto } from "../api.js";
import { icon } from "../icons.js";
import {
  CATEGORY_ICON,
  categoryLabel,
  statusLabel,
  fmtDist,
  pinCat,
  pinMarkup,
} from "../ui.js";

let map = null;
let markers = [];
let byKey = new Map();
let selectedKey = null;

const FRESH_MS = 6 * 60 * 60 * 1000;
const URGENCY = {
  medicine: 0,
  water: 1,
  groceries: 2,
  charging: 3,
  pets: 4,
  transport: 5,
  other: 6,
};

function pinIcon(kind, category, fresh) {
  return L.divIcon({
    className: "pin-wrap",
    html: pinMarkup(kind, category, fresh),
    iconSize: [44, 44],
    iconAnchor: [22, 22],
    popupAnchor: [0, -24],
  });
}

function isFresh(item, now = Date.now()) {
  const posted = Date.parse(item.created_at || "");
  return !Number.isNaN(posted) && now - posted >= 0 && now - posted <= FRESH_MS;
}

function postedAt(item) {
  const t = Date.parse(item.created_at || "");
  return Number.isNaN(t) ? 0 : t;
}

function stamp(item) {
  const t = postedAt(item);
  if (!t) return "";
  const when = new Date(t);
  const sameDay = when.toDateString() === new Date().toDateString();
  return sameDay
    ? when.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : when.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function oneLine(item) {
  const text = String(item.detail || "").replace(/\s+/g, " ").trim();
  if (text) return text;
  return `${categoryLabel(item.category)} · ${fmtDist(item.distance_m)}`;
}

function byUrgencyThenFreshness(a, b) {
  const rank = (it) => (it.type === "request" ? URGENCY[it.category] ?? 6 : 100);
  return rank(a) - rank(b) || postedAt(b) - postedAt(a);
}

function row(it, detail) {
  const isReq = it.type === "request";
  const when = stamp(it);
  const ico = isReq ? `cat-${pinCat(it.category)}` : "opp";
  return `<button type="button" class="near-row" data-id="${Number(it.id)}" data-type="${isReq ? "request" : "opportunity"}">
    <span class="near-ico ${ico}">${icon(CATEGORY_ICON[it.category] || "ellipsis", 16)}</span>
    <span class="near-text">
      <span class="near-title">${esc(it.title || categoryLabel(it.category))}</span>
      <span class="near-detail">${esc(detail)}</span>
    </span>
    <time class="near-time"${when ? ` datetime="${esc(it.created_at || "")}"` : ""}>${esc(when)}</time>
  </button>`;
}

// what the user has to do next on one of their own requests or claims
function mineLine(r) {
  if (r.is_mine && r.status === "claimed" && !r.accepted) return "A volunteer offered to help: accept or decline";
  if (r.is_mine && r.status === "completed") return "Marked done: confirm or reopen";
  if (r.is_mine && r.status === "claimed") return "Volunteer on the way";
  if (r.is_claimer && !r.accepted) return "Waiting for the resident to accept you";
  if (r.is_claimer) return "Accepted: help, then mark completed";
  return statusLabel(r.status);
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

export function renderMap(app) {
  if (map) {
    map.remove();
    map = null;
  }
  markers = [];
  byKey = new Map();
  selectedKey = null;

  app.innerHTML = `
    <div id="map"></div>
    <div class="deck">
      <div class="stack">
        <section class="sheet" id="areaCard">
          <div class="mine" id="mineBox" hidden>
            <h2 class="area-title">Yours</h2>
            <div class="near-list" id="mineList"></div>
          </div>
          <h1 class="area-title">Needs nearby</h1>
          <p class="area-count" id="areaCount">Searching…</p>
          <div class="near-list" id="nearList"></div>
          <div class="legend">
            <span><i class="pin-dot cat-charging"></i>Power</span>
            <span><i class="pin-dot cat-water"></i>Water / food</span>
            <span><i class="pin-dot cat-medicine"></i>Medical</span>
            <span><i class="pin-dot cat-pets"></i>Animals</span>
            <span><i class="pin-dot cat-other"></i>Other</span>
            <span><i class="pin-dot opp"></i>Offer</span>
          </div>
          <p class="fine">Need pins sit about 300 m from the real address.</p>
        </section>

        <section class="sheet detail" id="detailPanel" hidden>
          <button type="button" class="icon-btn detail-close" id="closeDetail" aria-label="Close">${icon("x", 18)}</button>
          <div id="detailBody"></div>
        </section>
      </div>
      <section class="sheet filters" id="filterCard">
          <div class="seg" role="group" aria-label="What to show">
            <button type="button" class="seg-btn on" data-kind="all">All</button>
            <button type="button" class="seg-btn" data-kind="request">Needs</button>
            <button type="button" class="seg-btn" data-kind="opportunity">Offers</button>
          </div>
          <input type="hidden" id="kind" value="all" />
          <label for="category">Category</label>
          <select id="category"><option value="">All categories</option></select>
          <div class="range-row">
            <label for="radius">Radius</label>
            <span class="range-val" id="radiusLabel">3 km</span>
          </div>
          <input type="range" id="radius" min="500" max="50000" step="500" value="3000" />
          <div class="filter-actions">
            <button type="button" class="btn btn-block" id="searchBtn">Search this area</button>
            <button type="button" class="btn secondary btn-block" id="hereBtn">${icon("locate", 16)} Use map center</button>
          </div>
          <p class="form-error" role="alert" id="searchMsg" hidden></p>
        </section>
    </div>
  `;

  const catSel = app.querySelector("#category");
  CATEGORIES.forEach((c) => {
    const o = document.createElement("option");
    o.value = c;
    o.textContent = categoryLabel(c);
    catSel.appendChild(o);
  });

  map = L.map(app.querySelector("#map"), { zoomControl: false }).setView([50.4501, 30.5234], 13);
  L.control.zoom({ position: "bottomright" }).addTo(map);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);
  requestAnimationFrame(() => map.invalidateSize());

  app.querySelector("#closeDetail").onclick = () => {
    app.querySelector("#detailPanel").hidden = true;
    selectedKey = null;
    markers.forEach((m) => m.getElement()?.classList.remove("is-selected"));
  };
  let searchAt = { lat: 50.4501, lng: 30.5234 };
  const useMapCenter = () => {
    const c = map.getCenter();
    searchAt = { lat: c.lat, lng: c.lng };
    search();
  };
  app.querySelector("#hereBtn").onclick = useMapCenter;
  app.querySelector("#searchBtn").onclick = useMapCenter;
  app.querySelector("#category").onchange = search;

  const radiusEl = app.querySelector("#radius");
  const radiusLabel = app.querySelector("#radiusLabel");
  radiusEl.addEventListener("input", () => {
    radiusLabel.textContent = fmtDist(radiusEl.value);
  });
  radiusEl.addEventListener("change", search);

  app.querySelectorAll(".seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      app.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("on", b === btn));
      app.querySelector("#kind").value = btn.dataset.kind;
      search();
    });
  });

  // Inline onclick="" is blocked by the API's CSP (script-src 'self'), so
  // action buttons are handled here by delegation.
  app.querySelector("#detailBody").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) act(btn);
  });

  // covers both the "Yours" list and the nearby list
  app.querySelector("#areaCard").addEventListener("click", (e) => {
    const row = e.target.closest(".near-row");
    if (!row) return;
    const key = `${row.dataset.type}:${row.dataset.id}`;
    const m = byKey.get(key);
    if (m) {
      markSelected(m, key);
      map.panTo(m.getLatLng());
    }
    if (row.dataset.type === "request") openDetail(row.dataset.id);
    else location.hash = `#/opportunities/${row.dataset.id}`;
  });

  window.__razomRefresh = () => {
    search();
    loadMine();
  };
  window.__razomRefresh();

  // Claimed and completed requests are not on the public map, so residents and
  // volunteers reach their own through this list (accept, complete, confirm).
  async function loadMine() {
    const roles = getUser()?.roles || [];
    const calls = [];
    if (roles.includes("resident")) calls.push(API.get("/me/requests"));
    if (roles.includes("volunteer")) calls.push(API.get("/me/claims"));
    const box = app.querySelector("#mineBox");
    if (!box || !calls.length) return;
    try {
      const seen = new Set();
      const items = (await Promise.all(calls)).flat().filter((r) => {
        if (seen.has(r.id)) return false;
        seen.add(r.id);
        return r.is_mine ? ["open", "claimed", "completed"].includes(r.status) : r.status === "claimed";
      });
      box.hidden = !items.length;
      app.querySelector("#mineList").innerHTML = items
        .map((r) => row({ ...r, type: "request" }, mineLine(r)))
        .join("");
    } catch {
      box.hidden = true;
    }
  }

  function markSelected(m, key) {
    selectedKey = key;
    markers.forEach((x) => x.getElement()?.classList.remove("is-selected"));
    m?.getElement()?.classList.add("is-selected");
  }

  function clearMarkers() {
    markers.forEach((m) => map.removeLayer(m));
    markers = [];
    byKey = new Map();
  }

  function paint(items) {
    const count = app.querySelector("#areaCount");
    const list = app.querySelector("#nearList");
    if (!count || !list) return;
    const needs = items.filter((it) => it.type === "request");
    const full = items.length >= 300;
    if (needs.length) count.textContent = full ? `${needs.length}+ open requests` : plural(needs.length, "open request", "open requests");
    else if (items.length) count.textContent = full ? `${items.length}+ offers` : plural(items.length, "offer", "offers");
    else count.textContent = "No open requests";

    list.innerHTML = items.slice().sort(byUrgencyThenFreshness).map((it) => row(it, oneLine(it))).join("");
  }

  async function search() {
    if (!app.querySelector("#areaCount")) return;
    const { lat, lng } = searchAt;
    const msg = app.querySelector("#searchMsg");
    const radius = app.querySelector("#radius").value || 3000;
    const cat = app.querySelector("#category").value;
    const kind = app.querySelector("#kind").value;
    let url = `/map?lat=${lat}&lng=${lng}&radius=${radius}&type=${kind}`;
    if (cat) url += `&category=${encodeURIComponent(cat)}`;
    msg.hidden = true;
    clearMarkers();
    try {
      const items = await API.get(url);
      paint(items);
      items.forEach((it) => {
        const isReq = it.type === "request";
        const key = `${it.type}:${it.id}`;
        const m = L.marker([it.latitude, it.longitude], {
          icon: pinIcon(isReq ? "req" : "opp", it.category, isFresh(it)),
        }).addTo(map);
        if (isReq) {
          m.on("click", () => {
            markSelected(m, key);
            openDetail(it.id);
          });
        } else {
          const when = it.start_time ? new Date(it.start_time).toLocaleString() : "Time not set";
          const slots = it.slots_left == null
            ? ""
            : `<div class="pop-meta">${Number(it.slots_left)} ${Number(it.slots_left) === 1 ? "slot" : "slots"} left</div>`;
          m.bindPopup(
            `<div class="pop">
              <div class="pop-kicker">Offer</div>
              <div class="pop-title">${esc(it.title || categoryLabel(it.category))}</div>
              <div class="pop-meta">${esc(categoryLabel(it.category))} · ${fmtDist(it.distance_m)}</div>
              <div class="pop-meta">${esc(when)}</div>
              ${slots}
            </div>`
          );
          m.on("click", () => markSelected(m, key));
        }
        markers.push(m);
        byKey.set(key, m);
      });
      if (selectedKey && byKey.has(selectedKey)) {
        byKey.get(selectedKey).getElement()?.classList.add("is-selected");
      }
    } catch (ex) {
      paint([]);
      msg.hidden = false;
      msg.textContent = ex.message;
    }
  }
}

const STATUS_CLASS = new Set(["open", "claimed", "completed", "confirmed", "cancelled"]);

async function openDetail(id) {
  const app = document.getElementById("app");
  const panel = app.querySelector("#detailPanel");
  const body = app.querySelector("#detailBody");
  if (!panel || !body) return;
  body.innerHTML = `<p class="area-sub">Loading…</p>`;
  panel.hidden = false;
  const user = getUser();
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
    // anyone except the author can report; the backend enforces ownership too
    if (!r.is_mine) {
      buttons.push(b("report", `${icon("flag", 15)} Report`, "secondary"));
    }

    const statusClass = STATUS_CLASS.has(r.status) ? r.status : "open";
    const where = r.exact_location
      ? `${Number(r.latitude).toFixed(5)}, ${Number(r.longitude).toFixed(5)}`
      : `${r.latitude != null ? Number(r.latitude).toFixed(3) : "?"}, ${r.longitude != null ? Number(r.longitude).toFixed(3) : "?"}`;
    const addr = r.exact_location && r.address
      ? `<div class="meta-row">${icon("house", 16)}<span>${esc(r.address)}</span></div>`
      : "";
    const claimer = r.claimer && r.is_mine
      ? `<div class="meta-row">${icon("user", 16)}<span>Claimed by <b>${esc(r.claimer.display_name)}</b>${r.claimer.is_verified ? ` ${icon("badgeCheck", 14)}` : ""}, helped ${Number(r.claimer.confirmed_count) || 0} times before</span></div>`
      : "";
    const hidden = r.is_hidden && r.is_mine
      ? `<div class="callout">${icon("alert", 16)}<span>This request was hidden by a moderator or by 3 reports. It's still visible to you.</span></div>`
      : "";
    let privacy;
    if (r.exact_location && r.is_claimer) {
      privacy = `<div class="callout">${icon("lock", 16)}<span>This address was shared with you. Opening it is recorded.</span></div>`;
    } else if (r.exact_location) {
      privacy = `<div class="callout">${icon("lock", 16)}<span>Exact address, visible to you.</span></div>`;
    } else {
      privacy = `<div class="callout quiet">${icon("lock", 16)}<span>Approximate location. The address stays hidden until a volunteer is accepted.</span></div>`;
    }
    const when = r.created_at ? new Date(r.created_at).toLocaleString() : "";
    const photoHolder = (r.claimer && r.is_mine && r.claimer.photo_url) || (r.is_claimer && r.author_photo_url)
      ? `<img id="partyPhoto" alt="" class="photo-thumb" style="margin-top:12px" />`
      : "";

    body.innerHTML = `
      <div class="detail-kicker cat-${pinCat(r.category)}">${icon(CATEGORY_ICON[r.category] || "ellipsis", 15)} ${esc(categoryLabel(r.category))}</div>
      <h2 class="detail-title">${esc(r.title || categoryLabel(r.category))}</h2>
      <span class="status ${statusClass}"><i></i>${esc(statusLabel(r.status))}</span>
      <p class="detail-desc">${esc(r.description)}</p>
      <div class="detail-meta">
        <div class="meta-row">${icon("pin", 16)}<span>${esc(where)}</span></div>
        ${addr}
        ${claimer}
        <div class="meta-row">${icon("clock", 16)}<span>${esc(when)}</span></div>
      </div>
      ${photoHolder}
      ${hidden}
      ${privacy}
      <div id="detailError" class="form-error" role="alert" hidden></div>
      <div class="actions">${buttons.join("") || '<span class="quiet-line">Nothing for you to do on this one.</span>'}</div>
    `;
    // load the other party's photo via fetch + blob URL (CSP: no plain <img src>)
    const photoPath = (r.claimer && r.is_mine && r.claimer.photo_url) || (r.is_claimer && r.author_photo_url);
    if (photoPath) {
      const img = body.querySelector("#partyPhoto");
      if (img) {
        loadPhoto(photoPath).then((url) => {
          if (url) img.src = url;
          else img.remove();
        });
      }
    }
  } catch (ex) {
    body.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`;
  }
}
function showActionError(message) {
  document.querySelectorAll("#detailPanel .btn").forEach((b) => {
    b.disabled = false;
  });
  const err = document.getElementById("detailError");
  if (err) {
    err.hidden = false;
    err.textContent = message;
  }
}

async function act(btn) {
  const { id, act: action, claim } = btn.dataset;
  if (action === "report") {
    return reportFlow(id);
  }
  if (action === "cancel" && !btn.dataset.sure) {
    btn.dataset.sure = "1";
    btn.textContent = "Confirm cancel";
    return;
  }
  document.querySelectorAll("#detailPanel .btn").forEach((b) => {
    b.disabled = true;
  });
  try {
    // accept/decline name the claim, so a stale page can't accept someone else
    await API.patch(`/requests/${id}/${action}`, claim ? { claim_id: Number(claim) } : undefined);
    if (action === "cancel" || action === "confirm") {
      const panel = document.getElementById("detailPanel");
      if (panel) panel.hidden = true;
    } else {
      openDetail(id);
    }
    window.__razomRefresh?.();
  } catch (ex) {
    showActionError(ex.message);
  }
}

// inline report: prompt for a reason, POST /api/reports, surface the result
async function reportFlow(requestId) {
  const reason = window.prompt("Why are you reporting this request? (3–500 characters)");
  if (!reason || !reason.trim()) return;
  const err = document.getElementById("detailError");
  try {
    await API.post("/reports", { target_type: "request", target_id: Number(requestId), reason: reason.trim() });
    if (err) {
      err.hidden = false;
      err.textContent = "Reported. Thank you.";
    }
  } catch (ex) {
    if (err) {
      err.hidden = false;
      err.textContent = ex.message;
    }
  }
}
