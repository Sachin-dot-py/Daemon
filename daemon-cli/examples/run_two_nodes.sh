#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EMU="$ROOT_DIR/examples/node-emulator/emulator.py"

BASE_MANIFEST="${BASE_MANIFEST:-$ROOT_DIR/examples/manifests/base.yml}"
ARM_MANIFEST="${ARM_MANIFEST:-$ROOT_DIR/examples/manifests/arm.yml}"
BASE_PORT="${BASE_PORT:-7777}"
ARM_PORT="${ARM_PORT:-7778}"

python3 "$EMU" --host 127.0.0.1 --port "$BASE_PORT" --manifest "$BASE_MANIFEST" &
PID1=$!
python3 "$EMU" --host 127.0.0.1 --port "$ARM_PORT" --manifest "$ARM_MANIFEST" &
PID2=$!

cleanup() {
  kill "$PID1" "$PID2" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait
