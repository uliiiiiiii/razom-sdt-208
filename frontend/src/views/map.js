// Map screen: radius search over requests + opportunities (GET /api/map).
// Click a request marker to open the detail panel and its lifecycle:
// claim -> resident accept/decline -> complete -> confirm/reopen -> cancel.
import L from "../leaflet-setup.js";
import { API, esc, getUser, CATEGORIES } from "../api.js";
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
          <p class="form-error" id="searchMsg" hidden></p>
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

  app.querySelector("#nearList").addEventListener("click", (e) => {
    const row = e.target.closest(".near-row");
    if (!row) return;
    const key = `${row.dataset.type}:${row.dataset.id}`;
    const m = byKey.get(key);
    if (m) {
      markSelected(m, key);
      map.panTo(m.getLatLng());
    }
    if (row.dataset.type === "request") openDetail(row.dataset.id);
    else if (m) m.openPopup();
  });

  window.__razomRefresh = search;
  search();

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
    if (needs.length) count.textContent = plural(needs.length, "open request", "open requests");
    else if (items.length) count.textContent = plural(items.length, "offer", "offers");
    else count.textContent = "No open requests";

    list.innerHTML = items.slice().sort(byUrgencyThenFreshness).map((it) => {
      const isReq = it.type === "request";
      const when = stamp(it);
      const ico = isReq ? `cat-${pinCat(it.category)}` : "opp";
      return `<button type="button" class="near-row" data-id="${Number(it.id)}" data-type="${isReq ? "request" : "opportunity"}">
        <span class="near-ico ${ico}">${icon(CATEGORY_ICON[it.category] || "ellipsis", 16)}</span>
        <span class="near-text">
          <span class="near-title">${esc(it.title || categoryLabel(it.category))}</span>
          <span class="near-detail">${esc(oneLine(it))}</span>
        </span>
        <time class="near-time"${when ? ` datetime="${esc(it.created_at || "")}"` : ""}>${esc(when)}</time>
      </button>`;
    }).join("");
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
    const buttons = [];
    if (user.roles.includes("volunteer") && r.status === "open" && !r.is_mine) {
      buttons.push(`<button class="btn" onclick="window.__razomAct(${id},'claim')">Claim</button>`);
    }
    if (r.is_mine && r.status === "claimed" && !r.accepted && r.claimer && r.claimer.claim_id != null) {
      const cid = Number(r.claimer.claim_id);
      buttons.push(`<button class="btn" onclick="window.__razomActClaim(${id},'accept',${cid})">Accept</button>`);
      buttons.push(`<button class="btn secondary" onclick="window.__razomActClaim(${id},'decline',${cid})">Decline</button>`);
    }
    if (r.is_claimer && r.status === "claimed" && r.accepted) {
      buttons.push(`<button class="btn" onclick="window.__razomAct(${id},'complete')">Mark completed</button>`);
      buttons.push(`<button class="btn secondary" onclick="window.__razomAct(${id},'release')">Release</button>`);
    }
    if (r.is_claimer && r.status === "claimed" && !r.accepted) {
      buttons.push(`<button class="btn secondary" onclick="window.__razomAct(${id},'release')">Release</button>`);
    }
    if (r.is_mine && (r.status === "open" || r.status === "claimed")) {
      buttons.push(`<button class="btn danger" id="cancelBtn" onclick="window.__razomAct(${id},'cancel')">Cancel request</button>`);
    }
    if (r.is_mine && r.status === "completed") {
      buttons.push(`<button class="btn" onclick="window.__razomAct(${id},'confirm')">Confirm received</button>`);
      buttons.push(`<button class="btn secondary" onclick="window.__razomAct(${id},'reopen')">Not resolved</button>`);
    }

    const statusClass = STATUS_CLASS.has(r.status) ? r.status : "open";
    const where = r.exact_location
      ? `${Number(r.latitude).toFixed(5)}, ${Number(r.longitude).toFixed(5)}`
      : `${r.latitude != null ? Number(r.latitude).toFixed(3) : "?"}, ${r.longitude != null ? Number(r.longitude).toFixed(3) : "?"}`;
    const addr = r.exact_location && r.address
      ? `<div class="meta-row">${icon("house", 16)}<span>${esc(r.address)}</span></div>`
      : "";
    const claimer = r.claimer && r.is_mine
      ? `<div class="meta-row">${icon("user", 16)}<span>Claimed by <b>${esc(r.claimer.display_name)}</b>, helped ${Number(r.claimer.confirmed_count) || 0} times before</span></div>`
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
      ${privacy}
      <div id="detailError" class="form-error" hidden></div>
      <div class="actions">${buttons.join("") || '<span class="quiet-line">Nothing for you to do on this one.</span>'}</div>
    `;
  } catch (ex) {
    body.innerHTML = `<div class="form-error">${esc(ex.message)}</div>`;
  }
}
window.openDetail = openDetail;

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

window.__razomAct = async function (id, action, confirmed) {
  if (action === "cancel" && !confirmed) {
    const btn = document.getElementById("cancelBtn");
    if (btn) {
      btn.textContent = "Confirm cancel";
      btn.onclick = () => window.__razomAct(id, "cancel", true);
    }
    return;
  }
  document.querySelectorAll("#detailPanel .btn").forEach((b) => {
    b.disabled = true;
  });
  try {
    await API.patch(`/requests/${id}/${action}`);
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
};

window.__razomActClaim = async function (id, action, claimId) {
  document.querySelectorAll("#detailPanel .btn").forEach((b) => {
    b.disabled = true;
  });
  try {
    await API.patch(`/requests/${id}/${action}`, { claim_id: claimId });
    openDetail(id);
    window.__razomRefresh?.();
  } catch (ex) {
    showActionError(ex.message);
  }
};
