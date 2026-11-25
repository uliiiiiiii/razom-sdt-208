import { API, setToken, setUser } from "../api.js";
import { authAside } from "../ui.js";

export function renderLogin(app) {
  app.innerHTML = `
    <div class="auth">
      ${authAside()}
      <div class="auth-main">
        <form class="auth-form" id="loginForm">
          <h1>Log in</h1>
          <p class="lede">Use the email you registered with.</p>
          <label for="email">Email</label>
          <input id="email" type="email" name="email" required autocomplete="username" placeholder="you@example.com" />
          <label for="password">Password</label>
          <input id="password" type="password" name="password" required autocomplete="current-password" placeholder="Your password" />
          <div id="err" class="form-error" role="alert" hidden></div>
          <button class="btn btn-block" type="submit" style="margin-top:16px">Log in</button>
          <p class="switch">New here? <a href="#/register">Create an account</a></p>
        </form>
      </div>
    </div>`;

  app.querySelector("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const err = app.querySelector("#err");
    const btn = e.target.querySelector("button[type=submit]");
    err.hidden = true;
    btn.disabled = true;
    try {
      const res = await API.post("/auth/login", {
        email: f.get("email"),
        password: f.get("password"),
      });
      setToken(res.access_token);
      // roles/is_verified come from the DB, not the 24 h token
      const me = await API.get("/auth/me");
      setUser({
        id: me.id,
        display_name: me.display_name,
        roles: me.roles,
        is_verified: me.is_verified,
        only_verified_residents: me.only_verified_residents,
      });
      location.hash = "#/";
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
      btn.disabled = false;
    }
  });
}
