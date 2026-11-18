import { icon } from "./icons.js";

export const CATEGORY_ICON = {
  charging: "zap",
  groceries: "bag",
  medicine: "pill",
  water: "droplet",
  transport: "car",
  pets: "paw",
  other: "ellipsis",
};

const CATEGORY_LABEL = {
  charging: "Charging",
  groceries: "Groceries",
  medicine: "Medicine",
  water: "Water",
  transport: "Transport",
  pets: "Pets",
  other: "Other",
};

const STATUS_LABEL = {
  open: "Open",
  claimed: "Claimed",
  completed: "Completed",
  confirmed: "Confirmed",
  cancelled: "Cancelled",
};

const PIN_CATS = new Set(["charging", "groceries", "medicine", "water", "transport", "pets", "other"]);

export function pinCat(category) {
  return PIN_CATS.has(category) ? category : "other";
}

export function categoryLabel(c) {
  return CATEGORY_LABEL[c] || c || "Other";
}

export function statusLabel(s) {
  return STATUS_LABEL[s] || s || "";
}

export function fmtDist(m) {
  if (m == null || Number.isNaN(Number(m))) return "–";
  const n = Number(m);
  if (n < 1000) return Math.round(n) + " m";
  const km = n / 1000;
  return (km < 10 ? km.toFixed(1) : Math.round(km).toString()) + " km";
}

export function pinMarkup(kind, category, fresh = false) {
  const cat = pinCat(category);
  const cls = ["pin", kind, `cat-${cat}`, fresh ? "fresh" : ""].filter(Boolean).join(" ");
  return `<div class="${cls}">${icon(CATEGORY_ICON[cat] || "ellipsis", 18)}</div>`;
}

export function authAside() {
  return `
    <aside class="auth-aside">
      <div class="brand on-dark">
        <span class="brand-sq" aria-hidden="true"></span>
        <span class="brand-name">Razom</span>
      </div>
      <div class="aside-copy">
        <h2>A charge, water, medicine, or a dog that needs a walk.</h2>
        <p>Posted on the map. Taken by someone close enough to show up.</p>
      </div>
      <div class="aside-foot">
        <div class="aside-num">300<span>m</span></div>
        <p>The public pin never lands on a door. An address is shown only to the person who asked and the volunteer they accept.</p>
        <p class="aside-credit">Map data © OpenStreetMap</p>
      </div>
    </aside>`;
}
