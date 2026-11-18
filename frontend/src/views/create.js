import L from "../leaflet-setup.js";
import { API, CATEGORIES } from "../api.js";
import { icon } from "../icons.js";
import { categoryLabel, pinMarkup } from "../ui.js";

let pickerMap = null;

function pinIcon(category) {
  return L.divIcon({
    className: "pin-wrap",
    html: pinMarkup("req", category),
    iconSize: [44, 44],
    iconAnchor: [22, 22],
  });
}

export function renderCreate(app) {
  if (pickerMap) {
    pickerMap.remove();
    pickerMap = null;
  }
  app.innerHTML = `
    <div class="compose">
      <form class="sheet compose-form" id="reqForm">
        <a class="back" href="#/">${icon("chevron", 16)} Map</a>
        <h1>Ask for help</h1>
        <p class="lede">Place a pin, then say what you need.</p>
        <label for="category">Category</label>
        <select name="category" id="category"></select>
        <label for="title">Title</label>
        <input id="title" name="title" maxlength="120" placeholder="Need a phone charged" />
        <label for="description">What you need</label>
        <textarea id="description" name="description" rows="4" required maxlength="2000" placeholder="Where to meet, what to bring, when it matters."></textarea>
        <label for="address">Address</label>
        <input id="address" name="address" maxlength="300" placeholder="Street, building, apartment" />
        <div id="err" class="form-error" hidden></div>
        <div class="compose-actions">
          <button class="btn" type="submit">Create request</button>
          <a href="#/" class="btn secondary">Cancel</a>
        </div>
        <p class="fine">${icon("lock", 14)}<span>The public pin is about 300 m from this point. The address is shown only to you and the volunteer you accept.</span></p>
      </form>
      <div class="compose-map">
        <div id="pickerMap"></div>
        <div class="compose-hint" id="coords">Click the map to place the pin</div>
      </div>
    </div>`;

  const sel = app.querySelector("#category");
  CATEGORIES.forEach((c) => {
    const o = document.createElement("option");
    o.value = c;
    o.textContent = categoryLabel(c);
    sel.appendChild(o);
  });

  pickerMap = L.map(app.querySelector("#pickerMap"), { zoomControl: false }).setView([50.4501, 30.5234], 13);
  L.control.zoom({ position: "bottomright" }).addTo(pickerMap);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(pickerMap);
  requestAnimationFrame(() => pickerMap.invalidateSize());

  let marker = null;
  let picked = null;
  sel.addEventListener("change", () => {
    if (marker) marker.setIcon(pinIcon(sel.value));
  });
  pickerMap.on("click", (e) => {
    picked = e.latlng;
    if (marker) marker.setLatLng(picked);
    else marker = L.marker(picked, { icon: pinIcon(sel.value) }).addTo(pickerMap);
    app.querySelector("#coords").textContent = picked.lat.toFixed(5) + ", " + picked.lng.toFixed(5);
  });

  app.querySelector("#reqForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = app.querySelector("#err");
    const btn = e.target.querySelector("button[type=submit]");
    err.hidden = true;
    if (!picked) {
      err.textContent = "Click the map to place the pin.";
      err.hidden = false;
      return;
    }
    const f = new FormData(e.target);
    const body = {
      category: f.get("category"),
      title: f.get("title") || null,
      description: f.get("description"),
      latitude: picked.lat,
      longitude: picked.lng,
      address: f.get("address") || null,
    };
    btn.disabled = true;
    try {
      await API.post("/requests", body);
      location.hash = "#/";
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
      btn.disabled = false;
    }
  });
}
