// Razom frontend — shared client logic (auth state + API calls + map UI).
// Talks to the FastAPI backend. Doubles as the UX/UI prototype.

const API = (() => {
  const base = ""; // same origin (backend serves frontend)
  function token() { return localStorage.getItem("razom_token"); }
  async function req(path, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    if (!(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
    const t = token();
    if (t) headers["Authorization"] = `Bearer ${t}`;
    const res = await fetch(base + path, { ...opts, headers });
    let data = null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) data = await res.json();
    else data = await res.text();
    if (!res.ok) {
      const msg = (data && data.detail) ? data.detail : (typeof data === "string" ? data : "Request failed");
      throw new Error(typeof msg === "object" ? JSON.stringify(msg) : msg);
    }
    return data;
  }
  return {
    token,
    setToken: (t) => localStorage.setItem("razom_token", t),
    clear: () => { localStorage.removeItem("razom_token"); localStorage.removeItem("razom_user"); },
    user: () => JSON.parse(localStorage.getItem("razom_user") || "null"),
    setUser: (u) => localStorage.setItem("razom_user", JSON.stringify(u)),
    get: (p) => req(p, { method: "GET" }),
    post: (p, body) => req(p, { method: "POST", body: JSON.stringify(body) }),
    patch: (p, body) => req(p, { method: "PATCH", body: JSON.stringify(body) }),
  };
})();

function logout() { API.clear(); location.href = "/login.html"; }

function renderUserBox() {
  const box = document.getElementById("userBox");
  if (!box) return;
  const u = API.user();
  if (u) {
    box.innerHTML = `<b>${u.display_name}</b> &middot; ${u.roles.join(", ")}
      <button class="btn secondary" style="margin-left:10px;padding:6px 12px" onclick="logout()">Logout</button>`;
  } else {
    box.innerHTML = `<a href="/login.html">Login</a> &middot; <a href="/register.html">Register</a>`;
  }
}

function requireAuth() {
  if (!API.token()) { location.href = "/login.html"; return false; }
  return true;
}

function fmtDist(m) { return m == null ? "-" : (m < 1000 ? Math.round(m) + " m" : (m/1000).toFixed(1) + " km"); }

const CATEGORIES = ["charging","groceries","medicine","water","transport","pets","other"];
