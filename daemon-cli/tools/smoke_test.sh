#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="$ROOT_DIR/daemon-cli/.venv"
TMP_DIR="$(mktemp -d)"
BASE_LOG="$TMP_DIR/base.log"
ARM_LOG="$TMP_DIR/arm.log"
RUN1_LOG="$TMP_DIR/run1.log"
RUN2_LOG="$TMP_DIR/run2.log"

BASE_PID=""
ARM_PID=""

log() {
  printf '[smoke] %s\n' "$1"
}

fail() {
  printf '[smoke] FAIL: %s\n' "$1" >&2
  exit 1
}

cleanup() {
  if [[ -n "$BASE_PID" ]] && kill -0 "$BASE_PID" 2>/dev/null; then
    kill "$BASE_PID" 2>/dev/null || true
  fi
  if [[ -n "$ARM_PID" ]] && kill -0 "$ARM_PID" 2>/dev/null; then
    kill "$ARM_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

cd "$ROOT_DIR"

log "Preparing venv"
python3 -m venv "$VENV_DIR"
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

log "Installing dependencies"
python3 -m pip install -r daemon-cli/requirements.txt >/dev/null
python3 -m pip install -e daemon-cli >/dev/null

log "Running CLI checks"
daemon --help >/dev/null

daemon build --firmware-dir daemon-cli/examples/annotated_firmware >/dev/null

log "Starting emulators"
python3 daemon-cli/examples/node-emulator/emulator.py --host 127.0.0.1 --port 7777 --manifest daemon-cli/examples/manifests/base.yml >"$BASE_LOG" 2>&1 &
BASE_PID=$!
python3 daemon-cli/examples/node-emulator/emulator.py --host 127.0.0.1 --port 7778 --manifest daemon-cli/examples/manifests/arm.yml >"$ARM_LOG" 2>&1 &
ARM_PID=$!

sleep 1
kill -0 "$BASE_PID" 2>/dev/null || fail "base emulator failed to start"
kill -0 "$ARM_PID" 2>/dev/null || fail "arm emulator failed to start"

ORCH_BASE_CMD=(python3 orchestrator/orchestrator.py --node base=localhost:7777 --node arm=localhost:7778)
if [[ -n "${PLANNER_URL:-}" ]]; then
  log "Running orchestrator one-shot with planner URL"
  ORCH_BASE_CMD+=(--planner-url "$PLANNER_URL")
else
  log "Running orchestrator one-shot with local fallback planner"
fi

"${ORCH_BASE_CMD[@]}" --instruction "forward then close gripper" >"$RUN1_LOG" 2>&1 || fail "orchestrator instruction 1 failed"
"${ORCH_BASE_CMD[@]}" --instruction "square" >"$RUN2_LOG" 2>&1 || fail "orchestrator instruction 2 failed"

grep -q "plan executed" "$RUN1_LOG" || fail "instruction 1 did not finish with 'plan executed'"
grep -q "plan executed" "$RUN2_LOG" || fail "instruction 2 did not finish with 'plan executed'"

log "PASS"
