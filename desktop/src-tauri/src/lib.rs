use local_ip_address::list_afinet_netifas;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

#[derive(Default)]
pub struct NodeState {
    child: Mutex<Option<CommandChild>>,
    port: Mutex<Option<u16>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StartNodeConfig {
    pub role: String,
    pub session: String,
    pub port: u16,
    pub peer: Option<String>,
    pub agent_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthResponse {
    pub status: String,
    pub agent_id: String,
    pub role: String,
    pub session_id: String,
    pub port: u16,
}

fn repo_root() -> PathBuf {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.parent().unwrap().parent().unwrap().to_path_buf()
}

fn data_dir(app: &AppHandle) -> PathBuf {
    let dir = app
        .path()
        .app_data_dir()
        .unwrap_or_else(|_| repo_root().join("crosslab-data"));
    fs::create_dir_all(&dir).ok();
    dir
}

fn node_args(config: &StartNodeConfig, data: &PathBuf) -> Vec<String> {
    let mut args = vec![
        "--role".to_string(),
        config.role.clone(),
        "--session".to_string(),
        config.session.clone(),
        "--port".to_string(),
        config.port.to_string(),
        "--data-dir".to_string(),
        data.to_string_lossy().to_string(),
        "--legacy-search-dir".to_string(),
        repo_root().to_string_lossy().to_string(),
    ];
    if let Some(peer) = &config.peer {
        if !peer.is_empty() {
            args.push("--peer".to_string());
            args.push(peer.clone());
        }
    }
    if let Some(agent_id) = &config.agent_id {
        if !agent_id.is_empty() {
            args.push("--agent-id".to_string());
            args.push(agent_id.clone());
        }
    }
    args
}

fn wait_for_health(port: u16, alive: &AtomicBool) -> Result<HealthResponse, String> {
    let url = format!("http://127.0.0.1:{}/health", port);
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;

    // Bundled PyInstaller sidecars can take 30-60s on a cold start while extracting.
    for _ in 0..120 {
        if !alive.load(Ordering::SeqCst) {
            return Err(
                "CrossLab node exited before it became ready. The port may already be in use."
                    .to_string(),
            );
        }
        if let Ok(resp) = client.get(&url).send() {
            if resp.status().is_success() {
                return resp.json().map_err(|e| format!("Invalid health response: {}", e));
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    Err(format!(
        "Node did not become healthy on port {} within 60 seconds",
        port
    ))
}

fn kill_node_process(state: &NodeState) {
    if let Some(child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
    }
    *state.port.lock().unwrap() = None;
}

#[tauri::command]
async fn start_node(
    app: AppHandle,
    state: State<'_, NodeState>,
    config: StartNodeConfig,
) -> Result<HealthResponse, String> {
    kill_node_process(&state);

    let data = data_dir(&app);
    let args = node_args(&config, &data);

    let alive = Arc::new(AtomicBool::new(true));
    let alive_watch = alive.clone();

    let (mut rx, child) = if cfg!(debug_assertions) {
        app.shell()
            .command("uv")
            .args(["run", "python", "-m", "crosslab.sidecar"])
            .args(args.clone())
            .current_dir(repo_root())
            .spawn()
            .or_else(|dev_err| {
                eprintln!("Dev sidecar failed ({dev_err}); falling back to bundled sidecar");
                app.shell()
                    .sidecar("crosslab-node")
                    .map_err(|e| format!("Bundled sidecar unavailable: {}", e))?
                    .args(args)
                    .spawn()
                    .map_err(|e| format!("Failed to spawn bundled sidecar: {}", e))
            })?
    } else {
        app.shell()
            .sidecar("crosslab-node")
            .map_err(|e| format!("Bundled sidecar unavailable: {}", e))?
            .args(args.clone())
            .spawn()
            .or_else(|bundled_err| {
                eprintln!("Bundled sidecar failed ({bundled_err}); falling back to dev sidecar");
                app.shell()
                    .command("uv")
                    .args(["run", "python", "-m", "crosslab.sidecar"])
                    .args(args)
                    .current_dir(repo_root())
                    .spawn()
                    .map_err(|e| format!("Failed to spawn dev sidecar: {}", e))
            })?
    };

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            if let CommandEvent::Terminated(payload) = event {
                alive_watch.store(false, Ordering::SeqCst);
                eprintln!("CrossLab sidecar terminated: {:?}", payload);
                break;
            }
        }
    });

    *state.child.lock().unwrap() = Some(child);
    *state.port.lock().unwrap() = Some(config.port);

    let port = config.port;
    let health = tauri::async_runtime::spawn_blocking(move || wait_for_health(port, &alive))
        .await
        .map_err(|e| format!("Health check task failed: {}", e))??;
    let _ = app.emit("node-started", &health);
    Ok(health)
}

#[tauri::command]
fn stop_node(state: State<'_, NodeState>) -> Result<(), String> {
    kill_node_process(&state);
    Ok(())
}

#[tauri::command]
fn get_node_port(state: State<'_, NodeState>) -> Option<u16> {
    *state.port.lock().unwrap()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NetworkEndpoint {
    pub ip: String,
    pub interface: String,
    pub kind: String,
    pub label: String,
    pub recommended: bool,
}

fn is_virtual_interface(name: &str) -> bool {
    let lower = name.to_lowercase();
    [
        "vethernet",
        "v ethernet",
        "wsl",
        "docker",
        "vmware",
        "virtualbox",
        "hyper-v",
        "virtual",
        "tunnel",
        "bluetooth",
        "npcap",
        "loopback",
        "default switch",
        "vbox",
        "tailscale", // tailscale has its own URL pattern
    ]
    .iter()
    .any(|keyword| lower.contains(keyword))
}

fn classify_ipv4(interface: &str, ip: std::net::Ipv4Addr) -> (String, String) {
    let octets = ip.octets();

    if octets[0] == 169 && octets[1] == 254 {
        return (
            "link_local".to_string(),
            "Link-local — only use if both PCs failed DHCP".to_string(),
        );
    }

    if is_virtual_interface(interface) {
        return (
            "virtual".to_string(),
            format!("Virtual adapter ({interface})"),
        );
    }

    if octets[0] == 172 && (17..=31).contains(&octets[1]) {
        return (
            "virtual".to_string(),
            format!("Virtual network ({interface})"),
        );
    }

    if octets[0] == 192 && octets[1] == 168 {
        return ("lan".to_string(), format!("Home / Wi-Fi LAN ({interface})"));
    }
    if octets[0] == 10 {
        return ("lan".to_string(), format!("Private LAN ({interface})"));
    }
    if octets[0] == 172 && (16..=31).contains(&octets[1]) {
        return ("lan".to_string(), format!("Private LAN ({interface})"));
    }

    ("other".to_string(), interface.to_string())
}

fn lan_priority(ip: std::net::Ipv4Addr) -> u8 {
    let octets = ip.octets();
    if octets[0] == 192 && octets[1] == 168 {
        return 0;
    }
    if octets[0] == 10 {
        return 1;
    }
    if octets[0] == 172 && (16..=31).contains(&octets[1]) {
        return 2;
    }
    3
}

#[tauri::command]
fn get_local_addresses() -> Vec<NetworkEndpoint> {
    let mut endpoints = Vec::new();
    if let Ok(ifaces) = list_afinet_netifas() {
        for (interface, ip) in ifaces {
            if !ip.is_ipv4() || ip.is_loopback() {
                continue;
            }
            let std_ip = match ip {
                std::net::IpAddr::V4(v4) => v4,
                _ => continue,
            };
            let (kind, label) = classify_ipv4(&interface, std_ip);
            endpoints.push(NetworkEndpoint {
                ip: std_ip.to_string(),
                interface,
                kind,
                label,
                recommended: false,
            });
        }
    }

    endpoints.sort_by(|a, b| {
        a.kind
            .cmp(&b.kind)
            .then_with(|| lan_priority(a.ip.parse().unwrap_or(std::net::Ipv4Addr::UNSPECIFIED)).cmp(
                &lan_priority(b.ip.parse().unwrap_or(std::net::Ipv4Addr::UNSPECIFIED)),
            ))
            .then(a.ip.cmp(&b.ip))
    });
    endpoints.dedup_by(|a, b| a.ip == b.ip);

    if let Some(best_ip) = endpoints
        .iter()
        .filter(|endpoint| endpoint.kind == "lan")
        .min_by_key(|endpoint| {
            lan_priority(endpoint.ip.parse().unwrap_or(std::net::Ipv4Addr::UNSPECIFIED))
        })
        .map(|endpoint| endpoint.ip.clone())
    {
        for endpoint in &mut endpoints {
            endpoint.recommended = endpoint.ip == best_ip;
        }
    }

    endpoints
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SavedSession {
    pub join_code: String,
    pub updated_at: u64,
    pub has_transcript: bool,
}

fn session_data_dirs(app: &AppHandle) -> Vec<PathBuf> {
    let app_data = data_dir(app);
    let legacy = repo_root();
    if legacy == app_data {
        vec![app_data]
    } else {
        vec![app_data, legacy]
    }
}

fn transcript_dirs(app: &AppHandle) -> Vec<PathBuf> {
    let mut dirs: Vec<PathBuf> = session_data_dirs(app)
        .iter()
        .map(|dir| dir.join("transcripts"))
        .collect();
    dirs.push(repo_root().join("transcripts"));
    dirs
}

fn parse_join_code(file_name: &str) -> Option<String> {
    if !file_name.starts_with("crosslab_") || !file_name.ends_with(".db") {
        return None;
    }
    let join_code = file_name
        .trim_start_matches("crosslab_")
        .trim_end_matches(".db")
        .to_string();
    if join_code.is_empty() {
        None
    } else {
        Some(join_code)
    }
}

fn collect_saved_sessions(app: &AppHandle) -> HashMap<String, (u64, u64)> {
    let mut sessions: HashMap<String, (u64, u64)> = HashMap::new();

    for dir in session_data_dirs(app) {
        let Ok(entries) = fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let file_name = entry.file_name().to_string_lossy().to_string();
            let Some(join_code) = parse_join_code(&file_name) else {
                continue;
            };
            let updated_at = entry
                .metadata()
                .ok()
                .and_then(|meta| meta.modified().ok())
                .map(system_time_ms)
                .unwrap_or(0);
            let size_bytes = entry.metadata().map(|meta| meta.len()).unwrap_or(0);
            let should_replace = match sessions.get(&join_code) {
                None => true,
                Some((_, existing_size)) => {
                    size_bytes > *existing_size
                        || (size_bytes == *existing_size && updated_at > sessions[&join_code].0)
                }
            };
            if should_replace {
                sessions.insert(join_code, (updated_at, size_bytes));
            }
        }
    }

    sessions
}

fn system_time_ms(time: SystemTime) -> u64 {
    time.duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

#[tauri::command]
fn list_saved_sessions(app: AppHandle) -> Vec<SavedSession> {
    let transcript_dirs = transcript_dirs(&app);
    let sessions = collect_saved_sessions(&app);
    let mut results = Vec::new();

    for (join_code, (updated_at, _size_bytes)) in sessions {
        let has_transcript = transcript_dirs
            .iter()
            .any(|dir| dir.join(format!("{join_code}.md")).exists());
        results.push(SavedSession {
            join_code,
            updated_at,
            has_transcript,
        });
    }

    results.sort_by(|a, b| b.updated_at.cmp(&a.updated_at));
    results
}

#[tauri::command]
async fn open_data_folder(app: AppHandle) -> Result<(), String> {
    let dir = data_dir(&app);
    tauri_plugin_opener::open_path(&dir, None::<&str>)
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn open_legacy_dashboard(app: AppHandle, port: u16) -> Result<(), String> {
    let label = "classic-hud";
    if let Some(window) = app.get_webview_window(label) {
        let _ = window.set_focus();
        return Ok(());
    }

    let url = format!("http://127.0.0.1:{}/dashboard", port);
    WebviewWindowBuilder::new(&app, label, WebviewUrl::External(url.parse().unwrap()))
        .title("CrossLab Classic HUD")
        .inner_size(1280.0, 800.0)
        .build()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
async fn open_legacy_in_browser(port: u16) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{}/dashboard", port);
    tauri_plugin_opener::open_url(url, None::<&str>).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .manage(NodeState::default())
        .invoke_handler(tauri::generate_handler![
            start_node,
            stop_node,
            get_node_port,
            get_local_addresses,
            list_saved_sessions,
            open_data_folder,
            open_legacy_dashboard,
            open_legacy_in_browser
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<NodeState>() {
                    kill_node_process(&state);
                }
            }
        });
}
