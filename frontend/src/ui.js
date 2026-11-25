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

/**
 * Show an inline prompt (textarea + submit/cancel) inside `container`.
 * Returns a Promise<string|null> — the trimmed text, or null if cancelled.
 */
export function inlinePrompt(container, question, opts = {}) {
  return new Promise((resolve) => {
    const { required = false, minlength = 0, maxlength = 500, placeholder = "" } = opts;
    container.hidden = false;
    container.innerHTML = `
      <label style="display:block;font-weight:600;margin-bottom:4px">${question}</label>
      <textarea rows="3" maxlength="${maxlength}" placeholder="${placeholder}" style="width:100%;margin-bottom:8px"></textarea>
      <div style="display:flex;gap:8px">
        <button class="btn" type="button">Submit</button>
        <button class="btn secondary" type="button">Cancel</button>
      </div>`;
    const ta = container.querySelector("textarea");
    const [submitBtn, cancelBtn] = container.querySelectorAll("button");
    const label = container.querySelector("label");
    ta.focus();
    cancelBtn.onclick = () => { container.innerHTML = ""; container.hidden = true; resolve(null); };
    submitBtn.onclick = () => {
      const val = ta.value.trim();
      if (required && val.length < minlength) {
        label.textContent = `${question} (at least ${minlength} characters required)`;
        ta.focus();
        return;
      }
      container.innerHTML = "";
      container.hidden = true;
      resolve(val);
    };
  });
}

/**
 * Show an inline confirmation (message + yes/cancel) inside `container`.
 * Returns a Promise<boolean>.
 */
export function inlineConfirm(container, question) {
  return new Promise((resolve) => {
    container.hidden = false;
    container.innerHTML = `
      <p style="font-weight:600;margin-bottom:8px">${question}</p>
      <div style="display:flex;gap:8px">
        <button class="btn danger" type="button">Yes, confirm</button>
        <button class="btn secondary" type="button">Cancel</button>
      </div>`;
    const [yesBtn, cancelBtn] = container.querySelectorAll("button");
    yesBtn.focus();
    yesBtn.onclick = () => { container.innerHTML = ""; container.hidden = true; resolve(true); };
    cancelBtn.onclick = () => { container.innerHTML = ""; container.hidden = true; resolve(false); };
  });
}

/**
 * Show a message (replaces alert) inside `container`.
 */
export function inlineNotice(container, message) {
  container.hidden = false;
  container.textContent = message;
}
