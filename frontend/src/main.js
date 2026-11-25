import "@fontsource/outfit/latin-500.css";
import "@fontsource/outfit/latin-600.css";
import "@fontsource/manrope/latin-400.css";
import "@fontsource/manrope/latin-500.css";
import "@fontsource/manrope/latin-600.css";
import "@fontsource/manrope/latin-700.css";
import "@fontsource/manrope/cyrillic-400.css";
import "@fontsource/manrope/cyrillic-500.css";
import "@fontsource/manrope/cyrillic-600.css";
import "@fontsource/manrope/cyrillic-700.css";
import "./styles.css";
import { getToken, esc } from "./api.js";
import { renderUserBox, requireAuth, refreshMe } from "./auth.js";
import { renderLogin } from "./views/login.js";
import { renderRegister } from "./views/register.js";
import { renderMap } from "./views/map.js";
import { renderCreate } from "./views/create.js";
import { renderRequest } from "./views/request.js";
import { renderOrganization } from "./views/organization.js";
import { renderOpportunity } from "./views/opportunity.js";
import { renderVerification } from "./views/verification.js";
import { renderModeration } from "./views/moderation.js";
import { icon } from "./icons.js";

const THEME_KEY = "razom_theme";

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById("themeBtn");
  if (!btn) return;
  const dark = theme === "dark";
  btn.innerHTML = icon(dark ? "sun" : "moon", 18);
  btn.setAttribute("aria-label", dark ? "Use light theme" : "Use dark theme");
}

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  const theme = saved === "dark" || saved === "light"
    ? saved
    : (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(theme);
  document.getElementById("themeBtn")?.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });
}

initTheme();

// routes with a parameter are functions of the param
function matchRoute(path) {
  if (path === "/login") return { view: renderLogin };
  if (path === "/register") return { view: renderRegister };
  if (path === "/create") return { view: renderCreate };
  if (path === "/verification") return { view: renderVerification };
  if (path === "/organization") return { view: renderOrganization };
  if (path === "/moderation") return { view: renderModeration };
  let m = path.match(/^\/requests\/(\d+)$/);
  if (m) return { view: renderRequest, param: m[1] };
  m = path.match(/^\/opportunities\/(\d+)$/);
  if (m) return { view: renderOpportunity, param: m[1] };
  if (path === "/") return { view: renderMap };
  return null;
}

async function router() {
  const path = location.hash.slice(1) || "/";
  const app = document.getElementById("app");
  const match = matchRoute(path);
  if (!match) {
    app.innerHTML = `<div class="page"><div class="card" style="text-align:center;padding:48px 24px"><h1>Page not found</h1><p>The page <code>${esc(path)}</code> doesn't exist.</p><a class="btn" href="#/">Back to map</a></div></div>`;
    return;
  }
  const isAuthScreen = path === "/login" || path === "/register";
  if (isAuthScreen && getToken()) {
    location.hash = "#/";
    return;
  }
  document.body.dataset.mode =
    path === "/" ? "map" : isAuthScreen ? "auth" : "page";
  app.innerHTML = "";
  if (!isAuthScreen) {
    if (!requireAuth()) return;
    // roles come from the DB, not the 24 h token: refresh on every navigation
    await refreshMe();
  }
  renderUserBox();
  match.view(app, match.param);
  // Move focus to the main content so screen readers announce the new view
  app.setAttribute("tabindex", "-1");
  app.focus({ preventScroll: true });
}

window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", router);
