# DAEMON Desktop App

Tauri + React app with a deterministic live camera loop for blue-cube picking demos.

## Features
- Live webcam preview (`640x480`)
- Downscaled frame capture (`320x240`, JPEG quality `0.6`, ~`3.3 FPS`)
- Sends frames to `POST /api/vision_step`
- Forwards returned plan to local orchestrator via Rust proxy command (`orchestrator_execute_plan`)
- Panic stop button wired via Rust proxy command (`orchestrator_stop`)
- UI panels for FSM state, perception/bbox overlay, debug metadata, and last plan

## Why orchestrator calls are proxied through Rust
WebView network restrictions can fail direct browser `fetch()` requests to local endpoints (`TypeError: Load failed`).
To make localhost orchestration reliable, React invokes Tauri Rust commands, and Rust performs HTTP requests to:
- `GET /status`
- `POST /execute_plan`
- `POST /stop`

## Run
```bash
npm install
npm run tauri dev
```

## Config
- `VITE_VERCEL_BASE_URL` (default `https://daemon-ten-chi.vercel.app`)
- `VITE_ORCHESTRATOR_BASE_URL` (default `http://127.0.0.1:5055`)

## Sleepy Test
1. Confirm orchestrator is reachable:
```bash
curl http://127.0.0.1:5055/status
```
2. Run Tauri app:
```bash
npm run tauri dev
```
3. Press `STOP` while live camera is running:
- Expect `STOP OK`
- If orchestrator is down, expect a clear Rust error string with URL + reason.

## Build checks
```bash
npm run build
cd src-tauri
cargo check
```

## One-command local demo
From repo root:
```bash
bash desktop-app/run.sh
```

This script starts:
- base emulator (`127.0.0.1:7777`)
- arm emulator (`127.0.0.1:7778`)
- orchestrator bridge (`127.0.0.1:5055`)
- Tauri desktop app (`npm run tauri dev`)

Ctrl+C in that terminal stops everything.
