import { API, clearAuth, getToken, getUser, setUser } from "./api.js";
import { icon } from "./icons.js";

const ROLE_LABEL = {
  resident: "Resident",
  volunteer: "Volunteer",
  organization: "Organization",
  moderator: "Moderator",
};

export function requireAuth() {
  if (!getToken()) {
    location.hash = "#/login";
    return false;
  }
  return true;
}

export function logout() {
  clearAuth();
  location.hash = "#/login";
}

// Roles are read from the database on every request, so a promoted or blocked user
// doesn't need a new token. Always trust /api/auth/me over the (24 h) login response.
export async function refreshMe() {
  if (!getToken()) return null;
  try {
    const me = await API.get("/auth/me");
    setUser({
      id: me.id,
      display_name: me.display_name,
      roles: me.roles,
      is_verified: me.is_verified,
      only_verified_residents: me.only_verified_residents,
    });
    return me;
  } catch (ex) {
    if (ex.status === 401 || ex.status === 403) {
      // token expired or account blocked
      clearAuth();
      location.hash = "#/login";
    }
    return null;
  }
}

export function renderUserBox() {
  const box = document.getElementById("userBox");
  const nav = document.getElementById("mainNav");
  if (!box || !nav) return;

  const path = location.hash.slice(1) || "/";
  const u = getUser();
  const authed = !!(u && getToken());
  const onAuth = path === "/login" || path === "/register";

  nav.innerHTML = "";
  box.replaceChildren();

  if (!authed || onAuth) return;

  const mapOn = path === "/" || path.startsWith("/requests/");
  const askOn = path === "/create";
  const verifyOn = path === "/verification";
  const orgOn = path === "/organization" || path.startsWith("/opportunities/");
  const modOn = path.startsWith("/moderation");
  const links = [
    `<a class="nav-item${mapOn ? " active" : ""}" href="#/" ${mapOn ? 'aria-current="page"' : ""}>${icon("map", 18)}<span>Map</span></a>`,
  ];
  if (u.roles?.includes("resident"))
    links.push(`<a class="nav-item${askOn ? " active" : ""}" href="#/create" ${askOn ? 'aria-current="page"' : ""}>${icon("plus", 18)}<span>Ask for help</span></a>`);
  if (u.roles?.includes("organization"))
    links.push(`<a class="nav-item${orgOn ? " active" : ""}" href="#/organization" ${orgOn ? 'aria-current="page"' : ""}>${icon("megaphone", 18)}<span>Offers</span></a>`);
  if (u.roles?.includes("volunteer") || u.roles?.includes("organization"))
    links.push(`<a class="nav-item${verifyOn ? " active" : ""}" href="#/verification" ${verifyOn ? 'aria-current="page"' : ""}>${icon("shieldCheck", 18)}<span>Verification</span></a>`);
  if (u.roles?.includes("moderator"))
    links.push(`<a class="nav-item${modOn ? " active" : ""}" href="#/moderation" ${modOn ? 'aria-current="page"' : ""}>${icon("shieldCheck", 18)}<span>Moderation</span></a>`);
  nav.innerHTML = links.join("");

  const avatar = document.createElement("span");
  avatar.className = "avatar";
  avatar.textContent = (u.display_name || "?").trim().charAt(0).toUpperCase() || "?";

  const who = document.createElement("div");
  who.className = "who";
  const name = document.createElement("span");
  name.className = "who-name";
  name.textContent = u.display_name || "";
  const role = document.createElement("span");
  role.className = "who-role";
  const roleText = (u.roles || []).map((r) => ROLE_LABEL[r] || r).join(", ");
  role.textContent = u.is_verified ? `${roleText} · verified` : roleText;
  who.append(name, role);

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "icon-btn";
  btn.setAttribute("aria-label", "Log out");
  btn.innerHTML = icon("logout", 18);
  btn.onclick = logout;

  if (u.is_verified) {
    const badge = document.createElement("span");
    badge.className = "avatar-badge";
    badge.title = "Verified";
    badge.innerHTML = icon("badgeCheck", 13);
    box.append(avatar, badge, who, btn);
  } else {
    box.append(avatar, who, btn);
  }
}
