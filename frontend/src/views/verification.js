// Identity verification (user side): #/verification
// Start a challenge, submit three images + document number, show status,
// and the only_verified_residents settings toggle.
import { API, esc, getUser } from "../api.js";
import { icon } from "../icons.js";

const STATUS_COPY = {
  none: "You haven't started verification yet.",
  started: "A challenge word is ready. Write it on paper, hold it in your selfie, and submit.",
  pending: "Your submission is waiting for a moderator to review it.",
  approved: "You're verified. You have a badge and a profile photo shown to the other party.",
  rejected: "Your verification was rejected. You can start again.",
  expired: "Your pending submission expired (no review within 30 days). You can start again.",
  revoked: "Your badge was revoked by a moderator. You can start again.",
};

export async function renderVerification(app) {
  app.innerHTML = `<div class="page"><p class="empty" role="status" aria-live="polite">Loading…</p></div>`;
  const page = app.querySelector(".page");
  let v;
  try { v = await API.get("/me/verification"); }
  catch (ex) { page.innerHTML = `<div class="form-error" role="alert">${esc(ex.message)}</div>`; return; }

  const canStart = v.status === "none" || ["rejected", "expired", "revoked"].includes(v.status);
  const canSubmit = v.status === "started";
  const copy = STATUS_COPY[v.status] || v.status;

  page.innerHTML = `
    <div class="page-head">${icon("shieldCheck", 24)}<h1>Verification</h1></div>
    <section class="card">
      <h2>Status</h2>
      <p class="card-sub">${esc(copy)}</p>
      ${v.comment ? `<div class="banner" style="margin-top:12px">${icon("info", 16)}<span>Moderator's note: ${esc(v.comment)}</span></div>` : ""}
      ${v.status === "started" && v.word ? `
        <div class="banner" style="margin-top:12px">${icon("info", 16)}<span>Challenge word: <b style="font-size:18px">${esc(v.word)}</b>${v.expires_at ? `<br>Valid until ${new Date(v.expires_at).toLocaleString()}` : ""}</span></div>
        <p class="field-hint">Write this word clearly on a piece of paper and hold it next to your face in the selfie.</p>
      ` : ""}
      <div class="actions" style="margin-top:14px">
        ${canStart ? `<button class="btn" id="startBtn">${v.status === "none" ? "Start verification" : "Start again"}</button>` : ""}
        ${canSubmit ? "" : ""}
      </div>
    </section>
    ${canSubmit ? `
      <section class="card" id="submitCard">
        <h2>Submit your documents</h2>
        <p class="card-sub">JPEG, PNG or WebP, at most 5 MB each. The server re-encodes and strips metadata.</p>
        <form id="vForm" style="margin-top:14px">
          <label for="v-id">ID document photo</label>
          <input id="v-id" name="id_document" type="file" accept="image/jpeg,image/png,image/webp" required />
          <label for="v-selfie">Selfie holding the challenge word</label>
          <input id="v-selfie" name="selfie" type="file" accept="image/jpeg,image/png,image/webp" required />
          <label for="v-profile">Profile photo</label>
          <input id="v-profile" name="profile" type="file" accept="image/jpeg,image/png,image/webp" required />
          <label for="v-docnum">Document number</label>
          <input id="v-docnum" name="document_number" required minlength="4" maxlength="32" placeholder="e.g. AB123456" />
          <p class="field-hint">4–32 characters. Stored only as a fingerprint to flag duplicates.</p>
          <div id="vErr" class="form-error" role="alert" hidden></div>
          <div class="compose-actions" style="margin-top:16px">
            <button class="btn" type="submit">Submit for review</button>
          </div>
        </form>
      </section>` : ""}
    <section class="card">
      <h2>Map preferences</h2>
      <label class="toggle" style="margin-top:12px">
        <input type="checkbox" id="vToggle" ${getUser()?.only_verified_residents ? "checked" : ""} />
        <span class="track"></span>
        <span style="font-size:14px;font-weight:600">Show only requests from verified residents</span>
      </label>
      <p class="field-hint">When on, the map hides requests from unverified authors.</p>
    </section>
  `;

  const startBtn = page.querySelector("#startBtn");
  if (startBtn) startBtn.onclick = async () => {
    startBtn.disabled = true;
    try { await API.post("/me/verification/start"); renderVerification(app); }
    catch (ex) { const e = document.createElement("div"); e.className = "form-error"; e.textContent = ex.message; startBtn.after(e); startBtn.disabled = false; }
  };

  const form = page.querySelector("#vForm");
  if (form) form.onsubmit = async (e) => {
    e.preventDefault();
    const err = page.querySelector("#vErr");
    err.hidden = true;
    const fd = new FormData(form);
    try {
      await API.postForm("/me/verification", fd);
      renderVerification(app);
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  };

  const toggle = page.querySelector("#vToggle");
  if (toggle) toggle.onchange = async () => {
    try { await API.patch("/me/settings", { only_verified_residents: toggle.checked }); }
    catch (ex) { toggle.checked = !toggle.checked; alert(ex.message); }
  };
}
