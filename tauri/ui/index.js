const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

const $ = (id) => document.getElementById(id);
const show = (id, on = true) => $(id).classList.toggle("hidden", !on);

const logEl = $("log");
listen("bootstrap-log", (e) => {
  logEl.textContent += e.payload + "\n";
  logEl.scrollTop = logEl.scrollHeight;
});

// Whether the keychain already has an API key stored — tracked separately
// from the (always-blank) #api_key field, since the raw key is never sent
// to this webview.
let hasApiKey = false;

$("backend").addEventListener("change", () => {
  const ollama = $("backend").value === "ollama";
  show("anthropic-fields", !ollama);
  show("ollama-fields", ollama);
});

// Show/hide toggle so a user can confirm the key they pasted.
$("toggle_key").addEventListener("click", () => {
  const field = $("api_key");
  const reveal = field.type === "password";
  field.type = reveal ? "text" : "password";
  $("toggle_key").textContent = reveal ? "hide" : "show";
  $("toggle_key").setAttribute("aria-label", reveal ? "Hide API key" : "Show API key");
});

function showSettings(prefill) {
  show("settings", true);
  show("progress", false);
  $("subtitle").textContent = "Configure your LLM backend to get started.";
  hasApiKey = Boolean(prefill && prefill.has_api_key);
  $("api_key").value = "";
  // Re-mask on (re)open so a newly typed key isn't left exposed from a prior reveal.
  $("api_key").type = "password";
  $("toggle_key").textContent = "show";
  $("toggle_key").setAttribute("aria-label", "Show API key");
  $("api_key").placeholder = hasApiKey
    ? "•••• saved, leave blank to keep"
    : "sk-ant-…";
  if (prefill) {
    $("backend").value = prefill.backend || "anthropic";
    $("gateway_url").value = prefill.gateway_url || "";
    $("ollama_url").value = prefill.ollama_url || "";
    $("classification_model").value = prefill.classification_model || "";
    $("extraction_model").value = prefill.extraction_model || "";
    $("backend").dispatchEvent(new Event("change"));
  }
}

function fail(msg) {
  show("settings", false);
  show("progress", true);
  $("stage-text").textContent = "Something went wrong";
  $("error").textContent = String(msg);
  show("retry", true);
  show("reconfigure", true);
}

async function start() {
  show("settings", false);
  show("progress", true);
  $("error").textContent = "";
  show("retry", false);
  show("reconfigure", false);
  try {
    const status = await invoke("get_status");
    if (!status.provisioned) {
      $("subtitle").textContent = "First run — setting up the local pipeline.";
      $("stage-text").textContent = "Installing Python runtime and dependencies (one-time, ~500 MB)…";
      await invoke("bootstrap");
    }
    $("subtitle").textContent = "Launching services…";
    $("stage-text").textContent = "Starting orchestrator, worker, and frontend…";
    const url = await invoke("launch");
    $("stage-text").textContent = "Ready — opening Orrery…";
    window.location.replace(url);
  } catch (e) {
    fail(e);
  }
}

$("save").addEventListener("click", async () => {
  const settings = {
    backend: $("backend").value,
    api_key: $("api_key").value.trim(),
    gateway_url: $("gateway_url").value.trim(),
    ollama_url: $("ollama_url").value.trim(),
    classification_model: $("classification_model").value.trim(),
    extraction_model: $("extraction_model").value.trim(),
  };
  const needsApiKey = settings.backend === "anthropic" && !settings.gateway_url && !hasApiKey;
  if (needsApiKey && !settings.api_key) {
    alert("Enter an Anthropic API key (or choose Ollama).");
    return;
  }
  try {
    await invoke("save_settings", { settings });
    start();
  } catch (e) {
    fail(e);
  }
});

$("retry").addEventListener("click", start);
$("reconfigure").addEventListener("click", async () => {
  const prefill = await invoke("get_settings").catch(() => null);
  showSettings(prefill);
});

(async function init() {
  try {
    const forceSettings = new URLSearchParams(window.location.search).get("settings") === "1";
    const status = await invoke("get_status");
    if (!status.has_settings || forceSettings) {
      const prefill = forceSettings
        ? await invoke("get_settings").catch(() => null)
        : null;
      showSettings(prefill);
    } else {
      start();
    }
  } catch (e) {
    fail(e);
  }
})();
