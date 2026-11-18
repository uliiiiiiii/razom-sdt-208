// Shared API client + auth storage + escaping helpers.
// Ported from the legacy js/app.js, adapted to ES modules and the Beta API.

const TOKEN_KEY = "razom_token";
const USER_KEY = "razom_user";
const BASE = "/api";

// must match the category CHECK constraints in the backend migrations
export const CATEGORIES = [
  "charging",
  "groceries",
  "medicine",
  "water",
  "transport",
  "pets",
  "other",
];

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t);
}
export function getUser() {
  return JSON.parse(localStorage.getItem(USER_KEY) || "null");
}
export function setUser(u) {
  localStorage.setItem(USER_KEY, JSON.stringify(u));
}
export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

// Escape user-supplied text before putting it into innerHTML.
export function esc(s) {
  return String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[c]
  );
}

const API_DOWN = "The API isn't responding. Start the backend on port 8000 and try again.";

function errorMessage(res, data) {
  const detail = data && typeof data === "object" ? data.detail : null;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const lines = detail
      .map((item) => {
        if (!item || typeof item !== "object" || !item.msg) return "";
        const loc = Array.isArray(item.loc)
          ? item.loc.filter((part) => part !== "body" && part !== "query").join(".")
          : "";
        return loc ? `${loc}: ${item.msg}` : item.msg;
      })
      .filter(Boolean);
    if (lines.length) return lines.join(" ");
  }
  if (typeof data === "string") {
    const text = data.trim();
    if (text && text.length < 300 && !/ECONNREFUSED|proxy error|\n\s+at /.test(text)) return text;
  }
  if (!res || res.status === 0 || res.status >= 500) return API_DOWN;
  return `The request failed (${res.status}).`;
}

async function req(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (!(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const t = getToken();
  if (t) headers["Authorization"] = `Bearer ${t}`;
  let res;
  try {
    res = await fetch(BASE + path, { ...opts, headers });
  } catch {
    const err = new Error(API_DOWN);
    err.status = 0;
    throw err;
  }
  let data = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) data = await res.json();
  else data = await res.text();
  if (!res.ok) {
    const err = new Error(errorMessage(res, data));
    err.status = res.status;
    throw err;
  }
  return data;
}

export const API = {
  get: (p) => req(p, { method: "GET" }),
  post: (p, body) => req(p, { method: "POST", body: JSON.stringify(body) }),
  patch: (p, body) =>
    req(p, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  del: (p) => req(p, { method: "DELETE" }),
};
