// ABOUTME: Shared desktop auto-update flow for the launch screen and the
// ABOUTME: manual "Check for Updates…" window. Browser globals only, no bundler.
const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

// Fail-open: resolve to `fallback` if `promise` doesn't settle within `ms`.
// A slow or hung update check must never keep the user out of the app.
function withTimeout(promise, ms, fallback) {
  return Promise.race([
    promise,
    new Promise((resolve) => setTimeout(() => resolve(fallback), ms)),
  ]);
}

// Inject the card CSS once, so both hosts render an identical card from one
// source (no duplicated styles across index.html and updates.html).
function ensureStyle() {
  if (document.getElementById("orrery-update-style")) return;
  const el = document.createElement("style");
  el.id = "orrery-update-style";
  el.textContent = `
    .ou-card { background:#141a2e; border:1px solid #232c4a; border-radius:12px;
      padding:20px; color:#dde3f0; font:15px/1.5 system-ui, sans-serif;
      width:min(520px,92vw); margin:0 auto; }
    .ou-title { font-size:18px; margin:0 0 8px; }
    .ou-notes { color:#8b94ad; font-size:13px; white-space:pre-wrap;
      max-height:180px; overflow-y:auto; margin:0 0 16px; }
    .ou-row { display:flex; gap:8px; }
    .ou-btn { padding:10px 18px; border-radius:8px; border:0; background:#5b6cff;
      color:#fff; font-weight:600; cursor:pointer; }
    .ou-btn.ghost { background:transparent; border:1px solid #2c3760; color:#aab3cc; }
    .ou-btn:disabled { opacity:.5; cursor:default; }
    .ou-bar { height:8px; background:#05070f; border-radius:6px; overflow:hidden;
      margin-top:14px; }
    .ou-bar > i { display:block; height:100%; width:0; background:#5b6cff;
      transition:width .15s linear; }
    .ou-status { color:#8b94ad; font-size:12px; margin-top:8px; }
    .ou-error { color:#ff8484; font-size:13px; white-space:pre-wrap; }
  `;
  document.head.appendChild(el);
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

async function runInstall(card, statusEl) {
  // Swap the buttons for a progress bar, then install. install_update restarts
  // the app on success, so control does not return here on the happy path.
  const bar = el("div", "ou-bar");
  const fill = el("i");
  bar.appendChild(fill);
  card.appendChild(bar);
  statusEl.textContent = "Downloading…";
  const un = await listen("update-progress", (e) => {
    const { downloaded, total } = e.payload;
    if (total) {
      fill.style.width = `${Math.min(100, Math.round((downloaded / total) * 100))}%`;
    }
    statusEl.textContent = `Downloading… ${Math.round(downloaded / 1e6)} MB`;
  });
  try {
    await invoke("install_update");
    un();
    statusEl.textContent = "Installing… the app will restart.";
  } catch (err) {
    un();
    fill.style.background = "#ff8484";
    statusEl.className = "ou-status ou-error";
    statusEl.textContent = `Update failed: ${String(err)}`;
  }
}

// mode: "launch" | "manual"
async function mountUpdateFlow({ container, mode, onDone }) {
  const done = typeof onDone === "function" ? onDone : () => {};
  try {
    ensureStyle();

    let info;
    try {
      info = await withTimeout(invoke("check_for_update"), 5000, { __timedOut: true });
    } catch (err) {
      info = { __error: String(err) };
    }

    // Fail-open on timeout: never block launch on a slow/hung check.
    if (info && info.__timedOut) {
      done();
      return;
    }

    const card = el("div", "ou-card");

    if (info && info.__error) {
      if (mode !== "manual") {
        done();
        return;
      }
      card.appendChild(el("h2", "ou-title", "Couldn't check for updates"));
      card.appendChild(el("p", "ou-error", info.__error));
      card.appendChild(el("p", "ou-notes", "You can close this window."));
      container.appendChild(card);
      return;
    }

    if (!info) {
      if (mode !== "manual") {
        done();
        return;
      }
      card.appendChild(el("h2", "ou-title", "You're up to date"));
      card.appendChild(el("p", "ou-notes", "You can close this window."));
      container.appendChild(card);
      return;
    }

    // An update is available.
    card.appendChild(el("h2", "ou-title", `Version ${info.version} is available`));
    if (info.notes) card.appendChild(el("p", "ou-notes", info.notes));
    const status = el("div", "ou-status");
    const row = el("div", "ou-row");
    const install = el("button", "ou-btn", "Install & Restart");
    const later = el("button", "ou-btn ghost", mode === "manual" ? "Close" : "Not now");
    row.appendChild(install);
    row.appendChild(later);
    card.appendChild(row);
    card.appendChild(status);
    container.appendChild(card);

    later.addEventListener("click", () => {
      card.remove();
      done();
    });
    install.addEventListener("click", async () => {
      install.disabled = true;
      later.disabled = true;
      await runInstall(card, status);
      // Reached only if the install failed — a successful install restarts the
      // app, so control never returns here. Re-enable dismiss so the user can
      // still proceed (in launch mode, dismissing is what boots the app).
      later.disabled = false;
    });
  } catch (err) {
    // Fail-open: an unexpected error must never hang launch (onDone gates boot).
    console.error("update flow failed:", err);
    done();
  }
}

window.OrreryUpdate = { mountUpdateFlow, withTimeout };
