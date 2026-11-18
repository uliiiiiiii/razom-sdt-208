import { clearAuth, getToken, getUser } from "./api.js";
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

  const mapOn = path === "/";
  const askOn = path === "/create";
  nav.innerHTML = `
    <a class="nav-item${mapOn ? " active" : ""}" href="#/" ${mapOn ? 'aria-current="page"' : ""}>${icon("map", 18)}<span>Map</span></a>
    <a class="nav-item${askOn ? " active" : ""}" href="#/create" ${askOn ? 'aria-current="page"' : ""}>${icon("plus", 18)}<span>Ask for help</span></a>
  `;

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
  role.textContent = (u.roles || []).map((r) => ROLE_LABEL[r] || r).join(", ");
  who.append(name, role);

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "icon-btn";
  btn.setAttribute("aria-label", "Log out");
  btn.innerHTML = icon("logout", 18);
  btn.onclick = logout;

  box.append(avatar, who, btn);
}
