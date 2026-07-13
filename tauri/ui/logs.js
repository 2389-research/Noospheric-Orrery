const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

const logEl = document.getElementById("log");
const pausedEl = document.getElementById("paused");
const MAX_DOM_LINES = 4000;
const enabled = { orchestrator: true, worker: true, frontend: true, bootstrap: false };
let autoscroll = true;

const ERR_RE = /error|traceback|exception|failed|fatal/i;

function addLine(service, line) {
  if (!(service in enabled)) enabled[service] = true;
  const div = document.createElement("div");
  div.className = "line " + service + (ERR_RE.test(line) ? " err" : "");
  const svc = document.createElement("span");
  svc.className = "svc";
  svc.textContent = service.padEnd(12);
  div.appendChild(svc);
  div.appendChild(document.createTextNode(line));
  div.style.display = enabled[service] ? "" : "none";
  logEl.appendChild(div);
  while (logEl.childElementCount > MAX_DOM_LINES) logEl.firstElementChild.remove();
  if (autoscroll) logEl.scrollTop = logEl.scrollHeight;
}

// Pause autoscroll when the user scrolls up; resume at bottom or via chip.
logEl.addEventListener("scroll", () => {
  const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 30;
  autoscroll = atBottom;
  pausedEl.style.display = atBottom ? "none" : "block";
});
pausedEl.addEventListener("click", () => {
  autoscroll = true;
  logEl.scrollTop = logEl.scrollHeight;
  pausedEl.style.display = "none";
});

document.querySelectorAll("input[data-svc]").forEach((cb) => {
  enabled[cb.dataset.svc] = cb.checked;
  cb.addEventListener("change", () => {
    enabled[cb.dataset.svc] = cb.checked;
    document.querySelectorAll(".line." + cb.dataset.svc).forEach((el) => {
      el.style.display = cb.checked ? "" : "none";
    });
    if (autoscroll) logEl.scrollTop = logEl.scrollHeight;
  });
});

document.getElementById("clear").addEventListener("click", () => {
  logEl.textContent = "";
});

(async function init() {
  // Subscribe before fetching history, so no line emitted while we're
  // awaiting get_log_buffer falls in the gap between the two calls.
  await listen("service-log", (e) => addLine(e.payload.service, e.payload.line));
  const history = await invoke("get_log_buffer");
  for (const [service, lines] of Object.entries(history)) {
    for (const line of lines) addLine(service, line);
  }
})();
