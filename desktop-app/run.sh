#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/desktop-app"

BASE_PORT="${BASE_PORT:-7777}"
ARM_PORT="${ARM_PORT:-7778}"
ORCH_PORT="${ORCH_PORT:-5055}"
ORCH_HOST="${ORCH_HOST:-127.0.0.1}"
BASE_HOST="${BASE_HOST:-127.0.0.1}"
ARM_HOST="${ARM_HOST:-127.0.0.1}"

EMULATOR_SCRIPT="$ROOT_DIR/daemon-cli/examples/node-emulator/emulator.py"
BASE_MANIFEST="$ROOT_DIR/daemon-cli/examples/manifests/base.yml"
ARM_MANIFEST="$ROOT_DIR/daemon-cli/examples/manifests/arm.yml"
ORCH_SCRIPT="$ROOT_DIR/orchestrator/orchestrator.py"

TMP_DIR="$(mktemp -d)"
BASE_LOG="$TMP_DIR/base.log"
ARM_LOG="$TMP_DIR/arm.log"
ORCH_LOG="$TMP_DIR/orchestrator.log"
KEEP_TMP="${KEEP_TMP:-0}"

BASE_PID=""
ARM_PID=""
ORCH_PID=""
PYTHON_BIN=""

log() {
  printf '[run] %s\n' "$1"
}

fail() {
  printf '[run] FAIL: %s\n' "$1" >&2
  KEEP_TMP=1
  if [[ -f "$BASE_LOG" ]]; then
    printf '[run] ---- base.log (tail) ----\n' >&2
    tail -n 40 "$BASE_LOG" >&2 || true
  fi
  if [[ -f "$ARM_LOG" ]]; then
    printf '[run] ---- arm.log (tail) ----\n' >&2
    tail -n 40 "$ARM_LOG" >&2 || true
  fi
  if [[ -f "$ORCH_LOG" ]]; then
    printf '[run] ---- orchestrator.log (tail) ----\n' >&2
    tail -n 60 "$ORCH_LOG" >&2 || true
  fi
  printf '[run] Logs kept at: %s\n' "$TMP_DIR" >&2
  exit 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

wait_http() {
  local url="$1"
  local timeout_s="${2:-20}"
  local started
  started="$(date +%s)"
  while true; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    if [[ $(( $(date +%s) - started )) -ge "$timeout_s" ]]; then
      return 1
    fi
    sleep 0.25
  done
}

kill_pid() {
  local pid="$1"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
  fi
}

cleanup() {
  log "Cleaning up background processes"
  kill_pid "$ORCH_PID"
  kill_pid "$ARM_PID"
  kill_pid "$BASE_PID"
  if [[ "$KEEP_TMP" == "1" ]]; then
    log "Keeping logs at: $TMP_DIR"
  else
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT INT TERM

ensure_python_runtime() {
  local daemon_venv="$ROOT_DIR/daemon-cli/.venv"
  local daemon_python="$daemon_venv/bin/python3"

  if [[ -x "$daemon_python" ]]; then
    PYTHON_BIN="$daemon_python"
  else
    PYTHON_BIN="$(command -v python3)"
  fi

  if "$PYTHON_BIN" -c "import yaml" >/dev/null 2>&1; then
    return 0
  fi

  log "PyYAML missing for $PYTHON_BIN; preparing daemon-cli/.venv"
  python3 -m venv "$daemon_venv"
  "$daemon_python" -m pip install -r "$ROOT_DIR/daemon-cli/requirements.txt" >/dev/null
  PYTHON_BIN="$daemon_python"
}

for cmd in python3 npm curl; do
  have_cmd "$cmd" || fail "Missing required command: $cmd"
done

ensure_python_runtime
log "Using Python runtime: $PYTHON_BIN"

if [[ ! -f "$EMULATOR_SCRIPT" ]]; then
  fail "Emulator script not found at $EMULATOR_SCRIPT"
fi
if [[ ! -f "$ORCH_SCRIPT" ]]; then
  fail "Orchestrator script not found at $ORCH_SCRIPT"
fi

cd "$ROOT_DIR"

if [[ ! -d "$APP_DIR/node_modules" ]]; then
  log "Installing desktop-app npm dependencies"
  (cd "$APP_DIR" && npm install)
fi

log "Starting base emulator on ${BASE_HOST}:${BASE_PORT}"
"$PYTHON_BIN" "$EMULATOR_SCRIPT" --host "$BASE_HOST" --port "$BASE_PORT" --manifest "$BASE_MANIFEST" >"$BASE_LOG" 2>&1 &
BASE_PID=$!

log "Starting arm emulator on ${ARM_HOST}:${ARM_PORT}"
"$PYTHON_BIN" "$EMULATOR_SCRIPT" --host "$ARM_HOST" --port "$ARM_PORT" --manifest "$ARM_MANIFEST" >"$ARM_LOG" 2>&1 &
ARM_PID=$!

sleep 1
kill -0 "$BASE_PID" 2>/dev/null || fail "Base emulator failed to start (see $BASE_LOG)"
kill -0 "$ARM_PID" 2>/dev/null || fail "Arm emulator failed to start (see $ARM_LOG)"

log "Starting orchestrator bridge on ${ORCH_HOST}:${ORCH_PORT}"
"$PYTHON_BIN" "$ORCH_SCRIPT" \
  --node base="${BASE_HOST}:${BASE_PORT}" \
  --node arm="${ARM_HOST}:${ARM_PORT}" \
  --http-host "$ORCH_HOST" \
  --http-port "$ORCH_PORT" >"$ORCH_LOG" 2>&1 &
ORCH_PID=$!

sleep 1
kill -0 "$ORCH_PID" 2>/dev/null || fail "Orchestrator failed to start (see $ORCH_LOG)"

if ! wait_http "http://${ORCH_HOST}:${ORCH_PORT}/status" 25; then
  fail "Orchestrator status endpoint not reachable on http://${ORCH_HOST}:${ORCH_PORT}/status (see $ORCH_LOG)"
fi

log "Orchestrator healthy: http://${ORCH_HOST}:${ORCH_PORT}/status"
log "Logs:"
log "  base emulator: $BASE_LOG"
log "  arm emulator:  $ARM_LOG"
log "  orchestrator:  $ORCH_LOG"

log "Launching desktop app (Ctrl+C to stop all)"
cd "$APP_DIR"
VITE_ORCHESTRATOR_BASE_URL="http://${ORCH_HOST}:${ORCH_PORT}" npm run tauri dev
