use serde::Serialize;
use serialport::SerialPort;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::Path;
use std::process::Command;
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::{AppHandle, Emitter, State};

const SERIAL_EVENT: &str = "serial_line";

#[derive(Clone)]
struct SerialSession {
    writer: Arc<Mutex<Box<dyn SerialPort + Send>>>,
    stop_tx: mpsc::Sender<()>,
    port_name: String,
}

#[derive(Clone)]
struct PiBridgeSession {
    target: String,
    host: String,
    port: u16,
    token: String,
    conn: Arc<Mutex<BufReader<TcpStream>>>,
}

#[derive(Default)]
struct AppState {
    session: Mutex<Option<SerialSession>>,
    pi_bridge: Mutex<Option<PiBridgeSession>>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SerialPortEntry {
    port_name: String,
    port_type: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ConnectionStatus {
    connected: bool,
    port_name: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct MecanumDispatchStatus {
    target: String,
    command: String,
    duration_ms: u32,
    serial_path: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PiBridgeDispatchStatus {
    target: String,
    command: String,
    duration_ms: u32,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PiBridgeConnectionStatus {
    connected: bool,
    target: Option<String>,
}

fn sanitize_identifier(value: &str, field_name: &str) -> Result<String, String> {
    if value.is_empty() {
        return Err(format!("{field_name} cannot be empty"));
    }

    if value
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || ch == '.' || ch == '-' || ch == '_')
    {
        Ok(value.to_string())
    } else {
        Err(format!("Invalid characters in {field_name}"))
    }
}

fn sanitize_serial_path(path: &str) -> Result<String, String> {
    if !path.starts_with("/dev/") {
        return Err("Serial path must start with /dev/".to_string());
    }

    if path
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || ch == '/' || ch == '.' || ch == '_' || ch == '-')
    {
        Ok(path.to_string())
    } else {
        Err("Serial path contains invalid characters".to_string())
    }
}

fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn normalize_mecanum_command(command: &str) -> Result<char, String> {
    let cmd = command
        .trim()
        .chars()
        .next()
        .ok_or_else(|| "Command cannot be empty".to_string())?
        .to_ascii_uppercase();

    match cmd {
        'F' | 'B' | 'L' | 'R' | 'Q' | 'E' | 'S' => Ok(cmd),
        _ => Err("Unsupported mecanum command (allowed: F,B,L,R,Q,E,S)".to_string()),
    }
}

fn resolve_sshpass_bin() -> String {
    // macOS GUI apps often don't inherit the interactive shell PATH.
    for candidate in ["/opt/homebrew/bin/sshpass", "/usr/local/bin/sshpass", "/usr/bin/sshpass"] {
        if Path::new(candidate).exists() {
            return candidate.to_string();
        }
    }
    "sshpass".to_string()
}

fn resolve_ssh_bin() -> String {
    for candidate in ["/usr/bin/ssh", "/bin/ssh"] {
        if Path::new(candidate).exists() {
            return candidate.to_string();
        }
    }
    "ssh".to_string()
}

fn resolve_socket_addrs(host: &str, port: u16) -> Result<Vec<SocketAddr>, String> {
    let addrs = (host, port)
        .to_socket_addrs()
        .map_err(|error| format!("Failed to resolve {host}:{port}: {error}"))?
        .collect::<Vec<_>>();
    if addrs.is_empty() {
        return Err(format!("No addresses found for {host}:{port}"));
    }
    Ok(addrs)
}

fn connect_pi_bridge_inner(host: &str, port: u16, token: &str) -> Result<PiBridgeSession, String> {
    let host_trimmed = host.trim();
    if host_trimmed.is_empty() {
        return Err("host cannot be empty".to_string());
    }

    let addrs = resolve_socket_addrs(host_trimmed, port)?;
    let mut last_error = None;

    for addr in addrs {
        match TcpStream::connect_timeout(&addr, Duration::from_secs(2)) {
            Ok(stream) => {
                // Per-command read timeout is set dynamically based on duration_ms.
                let _ = stream.set_read_timeout(Some(Duration::from_secs(20)));
                let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
                let _ = stream.set_nodelay(true);
                let target = format!("{host_trimmed}:{port}");
                return Ok(PiBridgeSession {
                    target,
                    host: host_trimmed.to_string(),
                    port,
                    token: token.to_string(),
                    conn: Arc::new(Mutex::new(BufReader::new(stream))),
                });
            }
            Err(error) => {
                last_error = Some(format!("Connect to {addr} failed: {error}"));
            }
        }
    }

    Err(last_error.unwrap_or_else(|| "Bridge connect failed".to_string()))
}

fn port_type_name(port_type: &serialport::SerialPortType) -> String {
    match port_type {
        serialport::SerialPortType::UsbPort(info) => {
            let mut label = String::from("usb");
            if let Some(product) = &info.product {
                label = format!("usb:{product}");
            }
            label
        }
        serialport::SerialPortType::BluetoothPort => String::from("bluetooth"),
        serialport::SerialPortType::PciPort => String::from("pci"),
        serialport::SerialPortType::Unknown => String::from("unknown"),
    }
}

fn emit_serial_line(app: &AppHandle, line: String) {
    let _ = app.emit(SERIAL_EVENT, line);
}

fn stop_session_locked(slot: &mut Option<SerialSession>) {
    if let Some(session) = slot.take() {
        let _ = session.stop_tx.send(());
    }
}

fn stop_pi_bridge_locked(slot: &mut Option<PiBridgeSession>) {
    *slot = None;
}

#[tauri::command]
fn list_serial_ports() -> Result<Vec<SerialPortEntry>, String> {
    let ports = serialport::available_ports().map_err(|error| error.to_string())?;
    let result = ports
        .into_iter()
        .map(|port| SerialPortEntry {
            port_name: port.port_name,
            port_type: port_type_name(&port.port_type),
        })
        .collect::<Vec<_>>();
    Ok(result)
}

#[tauri::command]
fn connect_serial(
    app: AppHandle,
    state: State<'_, AppState>,
    port_name: String,
    baud_rate: Option<u32>,
) -> Result<ConnectionStatus, String> {
    let baud = baud_rate.unwrap_or(115_200);

    let port = serialport::new(&port_name, baud)
        .timeout(Duration::from_millis(120))
        .open()
        .map_err(|error| format!("Failed to open serial port {port_name}: {error}"))?;

    let mut reader = port
        .try_clone()
        .map_err(|error| format!("Failed to clone serial reader: {error}"))?;

    let (stop_tx, stop_rx) = mpsc::channel::<()>();
    let writer: Arc<Mutex<Box<dyn SerialPort + Send>>> =
        Arc::new(Mutex::new(port as Box<dyn SerialPort + Send>));

    let app_handle = app.clone();
    thread::spawn(move || {
        let mut read_buf = [0_u8; 512];
        let mut pending = String::new();

        loop {
            if stop_rx.try_recv().is_ok() {
                break;
            }

            match reader.read(&mut read_buf) {
                Ok(size) if size > 0 => {
                    pending.push_str(&String::from_utf8_lossy(&read_buf[..size]));
                    while let Some(index) = pending.find('\n') {
                        let raw = pending[..index].trim().to_string();
                        pending.drain(..=index);
                        if !raw.is_empty() {
                            emit_serial_line(&app_handle, raw);
                        }
                    }
                }
                Ok(_) => {}
                Err(error) if error.kind() == std::io::ErrorKind::TimedOut => {}
                Err(error) => {
                    emit_serial_line(&app_handle, format!("ERR SERIAL_READ {error}"));
                    break;
                }
            }
        }
    });

    {
        let mut lock = state.session.lock().map_err(|_| "State lock poisoned".to_string())?;
        stop_session_locked(&mut lock);
        *lock = Some(SerialSession {
            writer,
            stop_tx,
            port_name: port_name.clone(),
        });
    }

    Ok(ConnectionStatus {
        connected: true,
        port_name: Some(port_name),
    })
}

#[tauri::command]
fn disconnect_serial(state: State<'_, AppState>) -> Result<ConnectionStatus, String> {
    let mut lock = state.session.lock().map_err(|_| "State lock poisoned".to_string())?;
    stop_session_locked(&mut lock);

    Ok(ConnectionStatus {
        connected: false,
        port_name: None,
    })
}

#[tauri::command]
fn connect_pi_bridge(
    state: State<'_, AppState>,
    host: String,
    port: u16,
    token: Option<String>,
) -> Result<PiBridgeConnectionStatus, String> {
    let token = token.unwrap_or_default();
    let session = connect_pi_bridge_inner(&host, port, token.trim())?;

    let mut lock = state.pi_bridge.lock().map_err(|_| "State lock poisoned".to_string())?;
    stop_pi_bridge_locked(&mut lock);
    *lock = Some(session.clone());

    Ok(PiBridgeConnectionStatus {
        connected: true,
        target: Some(session.target),
    })
}

#[tauri::command]
fn disconnect_pi_bridge(state: State<'_, AppState>) -> Result<PiBridgeConnectionStatus, String> {
    let mut lock = state.pi_bridge.lock().map_err(|_| "State lock poisoned".to_string())?;
    stop_pi_bridge_locked(&mut lock);
    Ok(PiBridgeConnectionStatus {
        connected: false,
        target: None,
    })
}

#[tauri::command]
fn get_pi_bridge_status(state: State<'_, AppState>) -> Result<PiBridgeConnectionStatus, String> {
    let lock = state.pi_bridge.lock().map_err(|_| "State lock poisoned".to_string())?;
    if let Some(session) = &*lock {
        Ok(PiBridgeConnectionStatus {
            connected: true,
            target: Some(session.target.clone()),
        })
    } else {
        Ok(PiBridgeConnectionStatus {
            connected: false,
            target: None,
        })
    }
}

#[tauri::command]
fn get_connection_status(state: State<'_, AppState>) -> Result<ConnectionStatus, String> {
    let lock = state.session.lock().map_err(|_| "State lock poisoned".to_string())?;
    if let Some(session) = &*lock {
        Ok(ConnectionStatus {
            connected: true,
            port_name: Some(session.port_name.clone()),
        })
    } else {
        Ok(ConnectionStatus {
            connected: false,
            port_name: None,
        })
    }
}

#[tauri::command]
fn send_serial_line(state: State<'_, AppState>, line: String) -> Result<(), String> {
    let lock = state.session.lock().map_err(|_| "State lock poisoned".to_string())?;
    let Some(session) = &*lock else {
        return Err("No active serial connection".to_string());
    };

    let mut writer = session
        .writer
        .lock()
        .map_err(|_| "Serial writer lock poisoned".to_string())?;

    writer
        .write_all(format!("{}\n", line.trim()).as_bytes())
        .map_err(|error| format!("Serial write failed: {error}"))?;
    writer
        .flush()
        .map_err(|error| format!("Serial flush failed: {error}"))?;

    Ok(())
}

#[tauri::command]
fn deploy_code_to_device(state: State<'_, AppState>, code: String) -> Result<u32, String> {
    let normalized = code.replace("\r\n", "\n");
    let lines = normalized.lines().collect::<Vec<_>>();

    if lines.is_empty() {
        return Err("No code content to deploy".to_string());
    }

    let lock = state.session.lock().map_err(|_| "State lock poisoned".to_string())?;
    let Some(session) = &*lock else {
        return Err("No active serial connection".to_string());
    };

    let mut writer = session
        .writer
        .lock()
        .map_err(|_| "Serial writer lock poisoned".to_string())?;

    writer
        .write_all(format!("BEGIN_CODE_UPLOAD {}\n", lines.len()).as_bytes())
        .map_err(|error| format!("Serial write failed: {error}"))?;

    for (index, line) in lines.iter().enumerate() {
        writer
            .write_all(format!("CODE {} {}\n", index + 1, line.trim_end()).as_bytes())
            .map_err(|error| format!("Serial write failed: {error}"))?;
    }

    writer
        .write_all(b"END_CODE_UPLOAD\n")
        .map_err(|error| format!("Serial write failed: {error}"))?;
    writer
        .flush()
        .map_err(|error| format!("Serial flush failed: {error}"))?;

    Ok(lines.len() as u32)
}

#[tauri::command]
fn send_mecanum_via_ssh(
    ssh_host: String,
    ssh_user: String,
    ssh_password: Option<String>,
    serial_path: String,
    baud_rate: Option<u32>,
    command: String,
    duration_ms: Option<u32>,
) -> Result<MecanumDispatchStatus, String> {
    let host = sanitize_identifier(ssh_host.trim(), "ssh_host")?;
    let user = sanitize_identifier(ssh_user.trim(), "ssh_user")?;
    let serial = sanitize_serial_path(serial_path.trim())?;
    let cmd = normalize_mecanum_command(&command)?;
    let baud = baud_rate.unwrap_or(9_600).clamp(1_200, 1_000_000);
    let hold_ms = duration_ms.unwrap_or(500).min(10_000);
    let target = format!("{user}@{host}");
    let password = ssh_password.unwrap_or_default();
    let use_password = !password.trim().is_empty();

    let hold_seconds = f64::from(hold_ms) / 1_000.0;
    let remote_script = if cmd == 'S' || hold_ms == 0 {
        format!(
            "python3 -c {python_code}",
            python_code = shell_quote(&format!(
                "import serial,time;s=serial.Serial({serial:?},{baud},timeout=1);time.sleep(2.0);s.write(b'S');s.flush();s.close()",
                serial = serial
            ))
        )
    } else {
        format!(
            "python3 -c {python_code}",
            python_code = shell_quote(&format!(
                "import serial,time;s=serial.Serial({serial:?},{baud},timeout=1);time.sleep(2.0);s.write(b'{cmd}');s.flush();time.sleep({hold_seconds:.3});s.write(b'S');s.flush();s.close()",
                serial = serial,
                cmd = cmd
            ))
        )
    };

    let ssh_bin = resolve_ssh_bin();
    let mut command_builder = if use_password {
        let sshpass_bin = resolve_sshpass_bin();
        let mut builder = Command::new(sshpass_bin);
        builder
            .arg("-p")
            .arg(password)
            .arg(ssh_bin)
            .arg("-o")
            .arg("ConnectTimeout=5")
            .arg("-o")
            .arg("PubkeyAuthentication=no")
            .arg("-o")
            .arg("PreferredAuthentications=password,keyboard-interactive")
            .arg("-o")
            .arg("StrictHostKeyChecking=accept-new")
            .arg(&target)
            .arg("sh")
            .arg("-lc")
            .arg(remote_script);
        builder
    } else {
        let mut builder = Command::new(ssh_bin);
        builder
            .arg("-o")
            .arg("BatchMode=yes")
            .arg("-o")
            .arg("ConnectTimeout=5")
            .arg(&target)
            .arg("sh")
            .arg("-lc")
            .arg(remote_script);
        builder
    };

    let output = command_builder.output().map_err(|error| {
        if use_password && error.kind() == std::io::ErrorKind::NotFound {
            "Failed to execute sshpass: install sshpass to use password authentication".to_string()
        } else {
            format!("Failed to execute ssh: {error}")
        }
    })?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let details = if !stderr.is_empty() {
            stderr
        } else if !stdout.is_empty() {
            stdout
        } else {
            format!("ssh exited with status {}", output.status)
        };
        return Err(format!("SSH dispatch failed: {details}"));
    }

    Ok(MecanumDispatchStatus {
        target,
        command: cmd.to_string(),
        duration_ms: hold_ms,
        serial_path: serial,
    })
}

#[tauri::command]
fn send_mecanum_via_pi_bridge(
    state: State<'_, AppState>,
    host: String,
    port: u16,
    token: Option<String>,
    command: String,
    duration_ms: Option<u32>,
) -> Result<PiBridgeDispatchStatus, String> {
    let host = host.trim().to_string();
    if host.is_empty() {
        return Err("host cannot be empty".to_string());
    }

    let cmd = normalize_mecanum_command(&command)?;
    let hold_ms = duration_ms.unwrap_or(500).min(10_000);
    let token = token.unwrap_or_default();

    // Reuse existing persistent connection when possible to avoid per-command connect latency.
    let maybe_session = {
        let lock = state.pi_bridge.lock().map_err(|_| "State lock poisoned".to_string())?;
        lock.clone()
    };

    let session = match maybe_session {
        Some(existing)
            if existing.host == host && existing.port == port && existing.token == token.trim() =>
        {
            existing
        }
        _ => {
            let new_session = connect_pi_bridge_inner(&host, port, token.trim())?;
            let mut lock = state.pi_bridge.lock().map_err(|_| "State lock poisoned".to_string())?;
            stop_pi_bridge_locked(&mut lock);
            *lock = Some(new_session.clone());
            new_session
        }
    };

    let request = serde_json::json!({
        "token": session.token,
        "cmd": cmd.to_string(),
        "duration_ms": hold_ms
    });
    let wire = format!("{}\n", request.to_string());

    let mut guard = session
        .conn
        .lock()
        .map_err(|_| "Bridge connection lock poisoned".to_string())?;

    // Allow the bridge to sleep up to duration_ms before responding, plus some slack.
    let _ = guard
        .get_mut()
        .set_read_timeout(Some(Duration::from_millis(hold_ms as u64 + 7_000)));

    guard
        .get_mut()
        .write_all(wire.as_bytes())
        .map_err(|error| format!("Bridge write failed: {error}"))?;
    guard
        .get_mut()
        .flush()
        .map_err(|error| format!("Bridge flush failed: {error}"))?;

    let mut line = String::new();
    let bytes = guard
        .read_line(&mut line)
        .map_err(|error| format!("Bridge read failed: {error}"))?;
    if bytes == 0 {
        // Peer closed; drop session so next call reconnects.
        let mut lock = state.pi_bridge.lock().map_err(|_| "State lock poisoned".to_string())?;
        stop_pi_bridge_locked(&mut lock);
        return Err("Bridge connection closed".to_string());
    }

    let resp: serde_json::Value =
        serde_json::from_str(line.trim()).map_err(|_| "Bridge returned invalid JSON".to_string())?;
    if resp.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        let err = resp
            .get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("bridge error");
        return Err(format!("Bridge rejected command: {err}"));
    }

    Ok(PiBridgeDispatchStatus {
        target: session.target,
        command: cmd.to_string(),
        duration_ms: hold_ms,
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(AppState::default())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            list_serial_ports,
            connect_serial,
            disconnect_serial,
            get_connection_status,
            send_serial_line,
            deploy_code_to_device,
            send_mecanum_via_ssh,
            send_mecanum_via_pi_bridge,
            connect_pi_bridge,
            disconnect_pi_bridge,
            get_pi_bridge_status
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
