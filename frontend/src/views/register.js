import { API, setToken, setUser } from "../api.js";
import { icon } from "../icons.js";
import { authAside } from "../ui.js";

export function renderRegister(app) {
  app.innerHTML = `
    <div class="auth">
      ${authAside()}
      <div class="auth-main">
        <form class="auth-form" id="regForm">
          <h1>Create an account</h1>
          <p class="lede">You can ask for help, offer it, or both.</p>
          <label for="display_name">Name</label>
          <input id="display_name" name="display_name" required autocomplete="name" placeholder="Your name" />
          <label for="email">Email</label>
          <input id="email" type="email" name="email" required autocomplete="email" placeholder="you@example.com" />
          <label for="password">Password</label>
          <input id="password" type="password" name="password" required minlength="8" autocomplete="new-password" placeholder="At least 8 characters" />
          <label>How you will use Razom</label>
          <div class="roles" id="roles">
            <label class="role-chip active">
              <input type="checkbox" name="is_resident" checked />
              ${icon("house", 18)}
              <span class="role-copy"><b>Resident</b><small>Post requests near home</small></span>
            </label>
            <label class="role-chip">
              <input type="checkbox" name="is_volunteer" />
              ${icon("help", 18)}
              <span class="role-copy"><b>Volunteer</b><small>Claim requests and join offers</small></span>
            </label>
            <label class="role-chip">
              <input type="checkbox" name="is_organization" />
              ${icon("building", 18)}
              <span class="role-copy"><b>Organization</b><small>Publish offers once verified</small></span>
            </label>
          </div>
          <div id="orgField" hidden>
            <label for="org_name">Organization name</label>
            <input id="org_name" name="org_name" placeholder="Help Kyiv" />
          </div>
          <div id="err" class="form-error" role="alert" hidden></div>
          <button class="btn btn-block" type="submit" style="margin-top:16px">Create account</button>
          <p class="switch">Already have an account? <a href="#/login">Log in</a></p>
        </form>
      </div>
    </div>`;

  app.querySelectorAll("#roles .role-chip input").forEach((cb) => {
    cb.addEventListener("change", () => cb.closest(".role-chip").classList.toggle("active", cb.checked));
  });
  const orgCb = app.querySelector('input[name="is_organization"]');
  const orgField = app.querySelector("#orgField");
  orgCb.addEventListener("change", () => {
    orgField.hidden = !orgCb.checked;
  });

  app.querySelector("#regForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const err = app.querySelector("#err");
    const btn = e.target.querySelector("button[type=submit]");
    err.hidden = true;
    const isOrg = !!f.get("is_organization");
    const body = {
      display_name: f.get("display_name"),
      email: f.get("email"),
      password: f.get("password"),
      is_resident: !!f.get("is_resident"),
      is_volunteer: !!f.get("is_volunteer"),
      is_organization: isOrg,
      org_name: isOrg ? f.get("org_name") || null : null,
    };
    btn.disabled = true;
    try {
      await API.post("/auth/register", body);
      const res = await API.post("/auth/login", { email: body.email, password: body.password });
      setToken(res.access_token);
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
