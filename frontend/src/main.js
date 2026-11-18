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
import { getToken } from "./api.js";
import { renderUserBox, requireAuth } from "./auth.js";
import { renderLogin } from "./views/login.js";
import { renderRegister } from "./views/register.js";
import { renderMap } from "./views/map.js";
import { renderCreate } from "./views/create.js";
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

const routes = {
  "/login": renderLogin,
  "/register": renderRegister,
  "/create": renderCreate,
  "/": renderMap,
};

function router() {
  const path = location.hash.slice(1) || "/";
  const app = document.getElementById("app");
  const view = routes[path];
  if (!view) {
    location.hash = "#/";
    return;
  }
  if ((path === "/login" || path === "/register") && getToken()) {
    location.hash = "#/";
    return;
  }
  document.body.dataset.mode =
    path === "/" ? "map" : path === "/login" || path === "/register" ? "auth" : "page";
  app.innerHTML = "";
  if (path !== "/login" && path !== "/register" && !requireAuth()) return;
  view(app);
  renderUserBox();
}

window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", router);
