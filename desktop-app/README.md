# DAEMON Desktop App (MVP)

Tauri + React desktop app for DAEMON-enabled devices.

## Features
- Enumerate serial ports
- Connect/disconnect to a selected port
- Send `HELLO` and `READ_MANIFEST`
- Parse and display DAEMON command catalog from `MANIFEST ...`
- Chat input with rule-based planner constrained to manifest commands
- Execute `RUN <TOKEN> <args>` and `STOP`
- Show `OK`/`ERR` responses and live `TELEMETRY ...` stream
- Realtime "Test on Device" loop:
  - Upload generated code to hardware over serial (`BEGIN_CODE_UPLOAD` / `CODE` / `END_CODE_UPLOAD`)
  - Request webcam + microphone and show local live preview
  - Stream periodic observation frames + audio level + telemetry to Vercel API evaluator
  - Receive `MATCH` or code-update suggestion and retry with one click

## Run
```bash
npm install
npm run tauri dev
```

## Realtime evaluator configuration

The desktop app sends evaluator requests to:

- `VITE_DAEMON_API_BASE_URL` (defaults to `http://localhost:3000`)

Example:

```bash
VITE_DAEMON_API_BASE_URL=https://your-vercel-api.vercel.app npm run tauri dev
```

## Build checks
```bash
npm run build
cd src-tauri
cargo check
```
