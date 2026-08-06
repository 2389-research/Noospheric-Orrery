// Noospheric supervisor: provisions Python environments with bundled uv,
// spawns the Orrery services (orchestrator, worker, frontend), and hands
// the window over to the frontend once everything is healthy.

use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{BufRead, BufReader};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager, State};

const ORCH_PORT: u16 = 8100;
const FRONT_PORT: u16 = 3100;
const LOG_BUFFER_LINES: usize = 1000;
const KEYRING_SERVICE: &str = "ai.2389.noospheric";
const KEYRING_USER: &str = "anthropic-api-key";

/// Fetch the Anthropic API key from the OS keychain (libsecret on Linux,
/// Keychain on macOS, Credential Manager on Windows). `None` if unset or the
/// keychain backend is unavailable.
fn keyring_get_api_key() -> Option<String> {
    keyring::Entry::new(KEYRING_SERVICE, KEYRING_USER)
        .ok()?
        .get_password()
        .ok()
}

/// Store the Anthropic API key in the OS keychain.
fn keyring_set_api_key(value: &str) -> Result<(), String> {
    keyring::Entry::new(KEYRING_SERVICE, KEYRING_USER)
        .map_err(|e| e.to_string())?
        .set_password(value)
        .map_err(|e| e.to_string())
}

#[derive(Default)]
struct Supervisor {
    children: Mutex<Vec<Child>>,
    /// Recent output per service, so the logs window can show history
    /// when opened after the fact.
    log_buffers: Mutex<HashMap<String, VecDeque<String>>>,
    /// The main window's URL at startup (the bundled index.html), captured
    /// once so "Change Settings" can navigate back to it later without
    /// guessing the asset protocol/origin.
    main_start_url: Mutex<Option<tauri::Url>>,
}

#[derive(Serialize, Clone)]
struct LogEvent {
    service: String,
    line: String,
}

/// Record one line of service output: in-memory tail, log file, and a
/// `service-log` event for the live logs window.
fn log_line(app: &tauri::AppHandle, paths: &Paths, service: &str, line: &str) {
    {
        let state: State<Supervisor> = app.state();
        let mut buffers = state.log_buffers.lock().unwrap();
        let buf = buffers.entry(service.to_string()).or_default();
        if buf.len() >= LOG_BUFFER_LINES {
            buf.pop_front();
        }
        buf.push_back(line.to_string());
    }
    if let Ok(mut f) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(paths.log(service))
    {
        use std::io::Write;
        let _ = writeln!(f, "{line}");
    }
    let _ = app.emit(
        "service-log",
        LogEvent {
            service: service.to_string(),
            line: line.to_string(),
        },
    );
}

#[derive(Serialize, Deserialize, Clone, Default)]
struct Settings {
    /// "anthropic" or "ollama"
    backend: String,
    #[serde(default)]
    api_key: String,
    #[serde(default)]
    gateway_url: String,
    #[serde(default)]
    ollama_url: String,
    #[serde(default)]
    classification_model: String,
    #[serde(default)]
    extraction_model: String,
}

/// What the webview is allowed to see: everything except the raw API key,
/// which stays in the OS keychain and Rust-side memory only.
#[derive(Serialize)]
struct SettingsView {
    backend: String,
    has_api_key: bool,
    gateway_url: String,
    ollama_url: String,
    classification_model: String,
    extraction_model: String,
}

#[derive(Serialize)]
struct Status {
    provisioned: bool,
    has_settings: bool,
    frontend_url: String,
}

struct Paths {
    resources: PathBuf,
    data: PathBuf,
}

impl Paths {
    fn resolve(app: &tauri::AppHandle) -> Result<Self, String> {
        let resources = app
            .path()
            .resource_dir()
            .map_err(|e| e.to_string())?
            .join("resources");
        let data = app.path().app_data_dir().map_err(|e| e.to_string())?;
        fs::create_dir_all(data.join("logs")).map_err(|e| e.to_string())?;
        fs::create_dir_all(data.join("runtime")).map_err(|e| e.to_string())?;
        fs::create_dir_all(data.join("orrery-data/documents")).map_err(|e| e.to_string())?;
        fs::create_dir_all(data.join("orrery-data/specs")).map_err(|e| e.to_string())?;
        Ok(Self { resources, data })
    }

    fn uv(&self) -> PathBuf {
        self.resources.join("bin/uv")
    }
    fn node(&self) -> PathBuf {
        self.resources.join("bin/node")
    }
    fn service(&self, name: &str) -> PathBuf {
        self.resources.join("services").join(name)
    }
    fn venv_python(&self, name: &str) -> PathBuf {
        self.data.join("runtime/venvs").join(name).join("bin/python")
    }
    fn settings_file(&self) -> PathBuf {
        self.data.join("settings.json")
    }
    fn stamp_file(&self) -> PathBuf {
        self.data.join("runtime/.provisioned")
    }
    fn log(&self, name: &str) -> PathBuf {
        self.data.join("logs").join(format!("{name}.log"))
    }
}

/// Content fingerprint of the bundled lockfiles; if it changes (app update),
/// we re-provision. FNV-1a — collisions just mean a redundant, idempotent
/// `uv sync`.
fn lockfiles_fingerprint(paths: &Paths) -> String {
    let mut acc: u64 = 0xcbf29ce484222325;
    for svc in ["orchestrator", "worker"] {
        if let Ok(bytes) = fs::read(paths.service(svc).join("uv.lock")) {
            for b in bytes {
                acc ^= b as u64;
                acc = acc.wrapping_mul(0x100000001b3);
            }
        }
    }
    format!("{acc:016x}")
}

fn is_provisioned(paths: &Paths) -> bool {
    fs::read_to_string(paths.stamp_file())
        .map(|s| s.trim() == lockfiles_fingerprint(paths))
        .unwrap_or(false)
}

fn uv_env(cmd: &mut Command, paths: &Paths, venv: &str) {
    cmd.env("UV_PYTHON_INSTALL_DIR", paths.data.join("runtime/python"))
        .env("UV_CACHE_DIR", paths.data.join("runtime/uv-cache"))
        .env(
            "UV_PROJECT_ENVIRONMENT",
            paths.data.join("runtime/venvs").join(venv),
        );
}

/// Run a command, streaming each output line to the UI as a `bootstrap-log`
/// event and appending to logs/bootstrap.log.
fn run_streaming(
    app: &tauri::AppHandle,
    paths: &Paths,
    mut cmd: Command,
    label: &str,
) -> Result<(), String> {
    let _ = app.emit("bootstrap-log", format!("$ {label}"));
    log_line(app, paths, "bootstrap", &format!("$ {label}"));
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = cmd.spawn().map_err(|e| format!("{label}: {e}"))?;
    let mut readers: Vec<Box<dyn BufRead + Send>> = Vec::new();
    if let Some(out) = child.stdout.take() {
        readers.push(Box::new(BufReader::new(out)));
    }
    if let Some(err) = child.stderr.take() {
        readers.push(Box::new(BufReader::new(err)));
    }
    let handles: Vec<_> = readers
        .into_iter()
        .map(|reader| {
            let app = app.clone();
            let paths = Paths {
                resources: paths.resources.clone(),
                data: paths.data.clone(),
            };
            std::thread::spawn(move || {
                for line in reader.lines().map_while(Result::ok) {
                    let _ = app.emit("bootstrap-log", line.clone());
                    log_line(&app, &paths, "bootstrap", &line);
                }
            })
        })
        .collect();
    let status = child.wait().map_err(|e| e.to_string())?;
    for h in handles {
        let _ = h.join();
    }
    if status.success() {
        Ok(())
    } else {
        Err(format!("{label} failed (exit {status}); see logs/bootstrap.log"))
    }
}

#[tauri::command]
fn get_status(app: tauri::AppHandle) -> Result<Status, String> {
    let paths = Paths::resolve(&app)?;
    Ok(Status {
        provisioned: is_provisioned(&paths),
        has_settings: paths.settings_file().exists(),
        frontend_url: format!("http://127.0.0.1:{FRONT_PORT}"),
    })
}

#[tauri::command]
fn get_settings(app: tauri::AppHandle) -> Result<SettingsView, String> {
    let paths = Paths::resolve(&app)?;
    let raw = fs::read_to_string(paths.settings_file()).map_err(|e| e.to_string())?;
    let settings: Settings = serde_json::from_str(&raw).map_err(|e| e.to_string())?;
    Ok(SettingsView {
        backend: settings.backend,
        has_api_key: keyring_get_api_key().is_some_and(|k| !k.is_empty()),
        gateway_url: settings.gateway_url,
        ollama_url: settings.ollama_url,
        classification_model: settings.classification_model,
        extraction_model: settings.extraction_model,
    })
}

#[tauri::command]
fn save_settings(app: tauri::AppHandle, mut settings: Settings) -> Result<(), String> {
    let paths = Paths::resolve(&app)?;
    // A non-empty incoming key replaces the stored one; an empty one means
    // "leave whatever's in the keychain alone" (the frontend never prefills
    // this field, so empty here means the user didn't touch it).
    if !settings.api_key.is_empty() {
        keyring_set_api_key(&settings.api_key)?;
    }
    settings.api_key.clear();
    let raw = serde_json::to_string_pretty(&settings).map_err(|e| e.to_string())?;
    fs::write(paths.settings_file(), raw).map_err(|e| e.to_string())
}

#[tauri::command]
async fn bootstrap(app: tauri::AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || bootstrap_impl(app))
        .await
        .map_err(|e| e.to_string())?
}

fn bootstrap_impl(app: tauri::AppHandle) -> Result<(), String> {
    let paths = Paths::resolve(&app)?;

    let mut cmd = Command::new(paths.uv());
    cmd.args(["python", "install", "3.12"]);
    uv_env(&mut cmd, &paths, "orchestrator");
    run_streaming(&app, &paths, cmd, "uv python install 3.12")?;

    for svc in ["orchestrator", "worker"] {
        let mut cmd = Command::new(paths.uv());
        cmd.args(["sync", "--frozen", "--no-dev", "--project"])
            .arg(paths.service(svc));
        uv_env(&mut cmd, &paths, svc);
        run_streaming(&app, &paths, cmd, &format!("uv sync ({svc})"))?;
    }

    // simmer-sdk is not in the worker lockfile (mirrors worker/Dockerfile):
    // install from the bundled source tree, with the [local] extra.
    let simmer = paths.service("simmer-sdk");
    if simmer.exists() {
        let req = format!("simmer-sdk[local] @ file://{}", simmer.to_string_lossy());
        let mut cmd = Command::new(paths.uv());
        cmd.args(["pip", "install", "--python"])
            .arg(paths.venv_python("worker"))
            .arg(&req);
        uv_env(&mut cmd, &paths, "worker");
        run_streaming(&app, &paths, cmd, "uv pip install simmer-sdk")?;
    }

    fs::write(paths.stamp_file(), lockfiles_fingerprint(&paths)).map_err(|e| e.to_string())?;
    Ok(())
}

fn or_default<'a>(value: &'a str, default: &'a str) -> &'a str {
    if value.is_empty() {
        default
    } else {
        value
    }
}

fn backend_env(cmd: &mut Command, settings: &Settings, paths: &Paths) {
    let data = paths.data.join("orrery-data");
    cmd.env("DB_PATH", data.join("orrery.db"))
        .env("DOCUMENTS_DIR", data.join("documents"))
        .env("SPECS_DIR", data.join("specs"))
        .env("AUTH_REQUIRED", "false")
        .env("NUMBA_THREADING_LAYER", "omp");
    if settings.backend == "ollama" {
        cmd.env("ANTHROPIC_BACKEND", "ollama")
            .env("OLLAMA_URL", or_default(&settings.ollama_url, "http://localhost:11434"))
            .env("CLASSIFICATION_MODEL", or_default(&settings.classification_model, "gemma4:26b"))
            .env("EXTRACTION_MODEL", or_default(&settings.extraction_model, "gemma4:e4b"));
    } else {
        cmd.env("ANTHROPIC_BACKEND", "gateway")
            .env("GATEWAY_URL", or_default(&settings.gateway_url, "https://api.anthropic.com"))
            .env("GATEWAY_API_KEY", &settings.api_key)
            .env("CLASSIFICATION_MODEL", or_default(&settings.classification_model, "claude-sonnet-4-6"))
            .env("EXTRACTION_MODEL", or_default(&settings.extraction_model, "claude-haiku-4-5"));
    }
}

/// Spawn a service child with stdout/stderr piped through reader threads
/// that feed log_line (file + buffer + live event stream).
fn spawn_logged(
    app: &tauri::AppHandle,
    paths: &Paths,
    service: &str,
    mut cmd: Command,
) -> Result<Child, String> {
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
    // Put each service in its own process group so the whole subtree (uvicorn /
    // node and any grandchildren they spawn) can be reaped together — otherwise
    // grandchildren orphan on quit, hold the ports, and block the next launch.
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }
    let mut child = cmd.spawn().map_err(|e| format!("{service}: {e}"))?;
    let mut readers: Vec<Box<dyn BufRead + Send>> = Vec::new();
    if let Some(out) = child.stdout.take() {
        readers.push(Box::new(BufReader::new(out)));
    }
    if let Some(err) = child.stderr.take() {
        readers.push(Box::new(BufReader::new(err)));
    }
    for reader in readers {
        let app = app.clone();
        let service = service.to_string();
        let paths = Paths {
            resources: paths.resources.clone(),
            data: paths.data.clone(),
        };
        std::thread::spawn(move || {
            for line in reader.lines().map_while(Result::ok) {
                log_line(&app, &paths, &service, &line);
            }
        });
    }
    Ok(child)
}

fn port_open(port: u16) -> bool {
    TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}").parse().unwrap(),
        Duration::from_millis(400),
    )
    .is_ok()
}

#[derive(Debug)]
enum WaitOutcome {
    Ready,
    Exited(String),
    TimedOut,
}

/// Poll until the service's port accepts connections, its child exits, or
/// the timeout lapses. The port is checked first: a served port means the
/// service is up even if the direct child handed off and exited.
fn wait_for_ready(
    port: u16,
    timeout: Duration,
    poll_interval: Duration,
    mut child_status: impl FnMut() -> Option<String>,
) -> WaitOutcome {
    let start = Instant::now();
    loop {
        if port_open(port) {
            return WaitOutcome::Ready;
        }
        if let Some(status) = child_status() {
            return WaitOutcome::Exited(status);
        }
        if start.elapsed() >= timeout {
            return WaitOutcome::TimedOut;
        }
        std::thread::sleep(poll_interval);
    }
}

/// Probe whether the service child at `idx` has exited; `None` while it
/// still runs or its status can't be read (the wait then falls back to
/// its timeout).
fn service_exit_probe(state: &Supervisor, idx: usize) -> impl FnMut() -> Option<String> + '_ {
    move || {
        let mut children = state.children.lock().unwrap();
        children
            .get_mut(idx)?
            .try_wait()
            .ok()
            .flatten()
            .map(|status| status.to_string())
    }
}

fn log_tail(paths: &Paths, name: &str) -> String {
    fs::read_to_string(paths.log(name))
        .map(|s| {
            let lines: Vec<&str> = s.lines().collect();
            lines[lines.len().saturating_sub(25)..].join("\n")
        })
        .unwrap_or_default()
}

fn wait_for_service(
    app: &tauri::AppHandle,
    paths: &Paths,
    name: &str,
    port: u16,
    timeout: Duration,
    child_status: impl FnMut() -> Option<String>,
) -> Result<(), String> {
    match wait_for_ready(port, timeout, Duration::from_millis(500), child_status) {
        WaitOutcome::Ready => Ok(()),
        WaitOutcome::Exited(status) => {
            // Through log_line, so the failure lands in the service's log
            // file (created on first write — a child that dies without
            // output otherwise leaves no file at all), the in-memory
            // buffer, and the live logs window.
            let died = format!("{name} exited ({status}) before becoming ready");
            log_line(app, paths, name, &died);
            Err(format!("{died}.\n\n{}", log_tail(paths, name)))
        }
        WaitOutcome::TimedOut => Err(format!(
            "{name} did not become ready on port {port}.\n\n{}",
            log_tail(paths, name)
        )),
    }
}

#[tauri::command]
async fn launch(app: tauri::AppHandle) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || launch_impl(app))
        .await
        .map_err(|e| e.to_string())?
}

fn launch_impl(app: tauri::AppHandle) -> Result<String, String> {
    let state: State<Supervisor> = app.state();
    // Kill any services from a previous launch (e.g. a settings change)
    // before spawning new ones — a no-op on first launch since nothing is
    // tracked yet.
    kill_children_and_clear_logs(&state);
    let paths = Paths::resolve(&app)?;
    let mut settings: Settings = {
        let raw = fs::read_to_string(paths.settings_file())
            .map_err(|_| "settings not configured".to_string())?;
        serde_json::from_str(&raw).map_err(|e| e.to_string())?
    };
    settings.api_key = keyring_get_api_key().unwrap_or_default();

    for (port, what) in [(ORCH_PORT, "orchestrator"), (FRONT_PORT, "frontend")] {
        if port_open(port) {
            return Err(format!(
                "Port {port} is already in use ({what}). Is another copy of Noospheric (or docker compose) running?"
            ));
        }
    }

    let orch_idx;
    let front_idx;
    {
        let mut children = state.children.lock().unwrap();

        let mut orch = Command::new(paths.venv_python("orchestrator"));
        orch.args([
            "-m",
            "uvicorn",
            "src.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            &ORCH_PORT.to_string(),
        ])
        .current_dir(paths.service("orchestrator"));
        backend_env(&mut orch, &settings, &paths);
        let _ = app.emit("bootstrap-log", "starting orchestrator…".to_string());
        orch_idx = children.len();
        children.push(spawn_logged(&app, &paths, "orchestrator", orch)?);

        let mut worker = Command::new(paths.venv_python("worker"));
        worker.args(["-m", "src.main"]).current_dir(paths.service("worker"));
        backend_env(&mut worker, &settings, &paths);
        let _ = app.emit("bootstrap-log", "starting worker…".to_string());
        children.push(spawn_logged(&app, &paths, "worker", worker)?);

        let mut front = Command::new(paths.node());
        front
            .arg("server.js")
            .current_dir(paths.resources.join("frontend"))
            .env("PORT", FRONT_PORT.to_string())
            .env("HOSTNAME", "127.0.0.1")
            .env("NODE_ENV", "production")
            .env("BACKEND_URL", format!("http://127.0.0.1:{ORCH_PORT}"));
        let _ = app.emit("bootstrap-log", "starting frontend…".to_string());
        front_idx = children.len();
        children.push(spawn_logged(&app, &paths, "frontend", front)?);
    }

    wait_for_service(
        &app,
        &paths,
        "orchestrator",
        ORCH_PORT,
        Duration::from_secs(90),
        service_exit_probe(state.inner(), orch_idx),
    )?;
    wait_for_service(
        &app,
        &paths,
        "frontend",
        FRONT_PORT,
        Duration::from_secs(60),
        service_exit_probe(state.inner(), front_idx),
    )?;
    let url = format!("http://127.0.0.1:{FRONT_PORT}");
    println!("✅ Services ready — {url}");
    let _ = app.emit("bootstrap-log", format!("Ready at {url}"));
    Ok(url)
}

#[tauri::command]
fn get_log_buffer(state: State<Supervisor>) -> HashMap<String, Vec<String>> {
    state
        .log_buffers
        .lock()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.iter().cloned().collect()))
        .collect()
}

fn open_logs_window(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("logs") {
        let _ = w.show();
        let _ = w.set_focus();
        return;
    }
    let _ = tauri::WebviewWindowBuilder::new(
        app,
        "logs",
        tauri::WebviewUrl::App("logs.html".into()),
    )
    .title("Noospheric — Service Logs")
    .inner_size(980.0, 640.0)
    .build();
}

/// Navigate the main window back to the bundled settings screen, marked
/// with `?settings=1` so index.html's init() shows the form immediately
/// (pre-filled with current values) instead of only on first run.
fn reopen_settings(app: &tauri::AppHandle) {
    let Some(main) = app.get_webview_window("main") else {
        return;
    };
    let Some(mut url) = app.state::<Supervisor>().main_start_url.lock().unwrap().clone() else {
        return;
    };
    url.set_query(Some("settings=1"));
    let _ = main.navigate(url);
}

fn kill_children(state: &Supervisor) {
    let mut children = state.children.lock().unwrap();
    // Graceful first: SIGTERM the whole process group of each service (negative
    // pgid == child pid, since each was spawned with process_group(0)).
    #[cfg(unix)]
    {
        for child in children.iter() {
            unsafe {
                libc::kill(-(child.id() as i32), libc::SIGTERM);
            }
        }
        // Brief grace period, then force-kill any survivors in the group — a
        // descendant that ignores SIGTERM would keep holding the port.
        if !children.is_empty() {
            std::thread::sleep(Duration::from_millis(500));
            for child in children.iter() {
                unsafe {
                    libc::kill(-(child.id() as i32), libc::SIGKILL);
                }
            }
        }
    }
    for child in children.iter_mut() {
        let _ = child.kill();
        let _ = child.wait();
    }
    children.clear();
}

/// Kill any running services and drop their buffered log history, so a
/// settings change followed by relaunch starts from a clean slate instead
/// of mixing old- and new-session log lines.
fn kill_children_and_clear_logs(state: &Supervisor) {
    kill_children(state);
    state.log_buffers.lock().unwrap().clear();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(Supervisor::default())
        .invoke_handler(tauri::generate_handler![
            get_status,
            get_settings,
            save_settings,
            bootstrap,
            launch,
            get_log_buffer
        ])
        .setup(|app| {
            println!("\n┌─ Noospheric ─────────────────────────────────");
            println!("│ Desktop window opened — complete setup there.");
            println!("│ After launch:");
            println!("│   Frontend  → http://127.0.0.1:{FRONT_PORT}");
            println!("│   API       → http://127.0.0.1:{ORCH_PORT}");
            println!("│   API docs  → http://127.0.0.1:{ORCH_PORT}/docs");
            println!("└──────────────────────────────────────────────\n");

            use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
            let logs_item =
                MenuItem::with_id(app, "view-logs", "Service Logs", true, Some("CmdOrCtrl+L"))?;
            let settings_item =
                MenuItem::with_id(app, "change-settings", "Change Settings…", true, None::<&str>)?;
            let quit = PredefinedMenuItem::quit(app, None)?;
            let submenu =
                Submenu::with_items(app, "Noospheric", true, &[&logs_item, &settings_item, &quit])?;
            // A custom menu overrides the default Edit menu; without these
            // predefined items, Cmd+X/C/V/A don't work in webview text fields
            // (e.g. pasting the API key into the settings form).
            let cut = PredefinedMenuItem::cut(app, None)?;
            let copy = PredefinedMenuItem::copy(app, None)?;
            let paste = PredefinedMenuItem::paste(app, None)?;
            let select_all = PredefinedMenuItem::select_all(app, None)?;
            // undo/redo are only supported on macOS in Tauri; on Windows/Linux
            // they'd render as inert menu items, so include them (and their
            // separator) only there.
            #[cfg(target_os = "macos")]
            let edit = {
                let undo = PredefinedMenuItem::undo(app, None)?;
                let redo = PredefinedMenuItem::redo(app, None)?;
                let sep = PredefinedMenuItem::separator(app)?;
                Submenu::with_items(
                    app,
                    "Edit",
                    true,
                    &[&undo, &redo, &sep, &cut, &copy, &paste, &select_all],
                )?
            };
            #[cfg(not(target_os = "macos"))]
            let edit =
                Submenu::with_items(app, "Edit", true, &[&cut, &copy, &paste, &select_all])?;
            let menu = Menu::with_items(app, &[&submenu, &edit])?;
            app.set_menu(menu)?;

            if let Some(main) = app.get_webview_window("main") {
                let start_url = main.url()?;
                *app.state::<Supervisor>().main_start_url.lock().unwrap() = Some(start_url);
            }

            // Window close kills the services via on_window_event, but a
            // SIGTERM/SIGHUP (logout, kill) bypasses that and orphans them.
            #[cfg(unix)]
            {
                use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM};
                let handle = app.handle().clone();
                std::thread::spawn(move || {
                    let mut signals =
                        signal_hook::iterator::Signals::new([SIGTERM, SIGINT, SIGHUP])
                            .expect("failed to register signal handler");
                    if signals.forever().next().is_some() {
                        kill_children(&handle.state::<Supervisor>());
                        std::process::exit(0);
                    }
                });
            }
            Ok(())
        })
        .on_menu_event(|app, event| {
            if event.id() == "view-logs" {
                open_logs_window(app);
            } else if event.id() == "change-settings" {
                reopen_settings(app);
            }
        })
        .on_window_event(|window, event| {
            // Only the main window owns the services; closing the logs
            // window must not take the app down.
            if window.label() == "main" {
                if let tauri::WindowEvent::Destroyed = event {
                    kill_children(&window.state::<Supervisor>());
                    window.app_handle().exit(0);
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                kill_children(&app.state::<Supervisor>());
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    const FAST_POLL: Duration = Duration::from_millis(10);

    /// Bind an ephemeral port, then release it so nothing is listening there.
    fn closed_port() -> u16 {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.local_addr().unwrap().port()
    }

    #[test]
    fn ready_when_port_opens() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let outcome = wait_for_ready(port, Duration::from_secs(5), FAST_POLL, || None);
        assert!(matches!(outcome, WaitOutcome::Ready));
    }

    #[test]
    fn ready_wins_when_port_open_and_child_exited() {
        // A served port means launch succeeded even if the direct child
        // handed off to a grandchild and exited; exit is only a heuristic.
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let outcome = wait_for_ready(port, Duration::from_secs(5), FAST_POLL, || {
            Some("exit status: 0".to_string())
        });
        assert!(matches!(outcome, WaitOutcome::Ready));
    }

    #[test]
    fn exited_child_reported_before_timeout() {
        // Generous timeout: a wait loop that ignores the exit probe fails
        // this test by returning TimedOut instead.
        let outcome = wait_for_ready(closed_port(), Duration::from_secs(30), FAST_POLL, || {
            Some("signal: 5 (SIGTRAP)".to_string())
        });
        match outcome {
            WaitOutcome::Exited(status) => assert_eq!(status, "signal: 5 (SIGTRAP)"),
            other => panic!("expected Exited, got {other:?}"),
        }
    }

    #[test]
    fn times_out_when_no_ready_no_exit() {
        let outcome = wait_for_ready(
            closed_port(),
            Duration::from_millis(50),
            FAST_POLL,
            || None,
        );
        assert!(matches!(outcome, WaitOutcome::TimedOut));
    }

    #[cfg(unix)]
    #[test]
    fn probe_none_while_child_runs() {
        let supervisor = Supervisor::default();
        let child = Command::new("sleep").arg("30").spawn().unwrap();
        supervisor.children.lock().unwrap().push(child);
        let mut probe = service_exit_probe(&supervisor, 0);
        assert_eq!(probe(), None);
        kill_children(&supervisor);
    }

    #[cfg(unix)]
    #[test]
    fn probe_reports_real_child_exit() {
        let supervisor = Supervisor::default();
        let child = Command::new("false").spawn().unwrap();
        supervisor.children.lock().unwrap().push(child);
        let mut probe = service_exit_probe(&supervisor, 0);
        let deadline = Instant::now() + Duration::from_secs(5);
        let status = loop {
            if let Some(status) = probe() {
                break status;
            }
            assert!(Instant::now() < deadline, "child exit never reported");
            std::thread::sleep(FAST_POLL);
        };
        assert!(
            status.contains("exit status: 1"),
            "unexpected status: {status}"
        );
    }
}
