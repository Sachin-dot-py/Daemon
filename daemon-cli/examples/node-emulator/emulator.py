#!/usr/bin/env python3
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

HOST = "127.0.0.1"
PORT = 7777

MANIFEST = {
    "daemon_version": "0.1",
    "device": {"name": "node-emulator", "version": "0.1.0", "node_id": "node-emulator-1"},
    "commands": [
        {
            "token": "L",
            "description": "Turn left",
            "args": [{"name": "intensity", "type": "int", "min": 0, "max": 255, "required": True}],
            "safety": {"rate_limit_hz": 20, "watchdog_ms": 300, "clamp": True},
            "nlp": {"synonyms": ["left", "turn left"], "examples": ["turn left 120"]},
        },
        {
            "token": "FWD",
            "description": "Move forward",
            "args": [{"name": "speed", "type": "int", "min": 0, "max": 100, "required": True}],
            "safety": {"rate_limit_hz": 10, "watchdog_ms": 500, "clamp": True},
            "nlp": {"synonyms": ["forward", "go ahead"], "examples": ["forward 50"]},
        },
    ],
    "telemetry": {"keys": [{"name": "uptime_ms", "type": "int", "unit": "ms"}, {"name": "last_token", "type": "string"}]},
    "transport": {"type": "serial-line-v1"},
}


class ClientState:
    def __init__(self, conn: socket.socket):
        self.conn = conn
        self.running = True
        self.last_token = "NONE"


def send_line(conn: socket.socket, line: str) -> None:
    conn.sendall((line + "\n").encode("utf-8"))


def parse_run(line: str):
    parts = line.strip().split()
    if len(parts) < 2:
        return None, []
    return parts[1], parts[2:]


def handle_run(state: ClientState, token: str, args: list[str]) -> str:
    if token == "STOP":
        state.last_token = "STOP"
        return "OK"

    command = next((c for c in MANIFEST["commands"] if c["token"] == token), None)
    if not command:
        return "ERR BAD_TOKEN unknown"

    expected_args = command["args"]
    if len(args) != len(expected_args):
        return "ERR BAD_ARGS wrong_count"

    for idx, arg_spec in enumerate(expected_args):
        raw = args[idx]
        if arg_spec["type"] in {"int", "float"}:
            try:
                value = float(raw)
            except ValueError:
                return "ERR BAD_ARGS parse"

            min_v = arg_spec.get("min")
            max_v = arg_spec.get("max")
            if min_v is not None and value < float(min_v):
                if command["safety"].get("clamp", True):
                    value = float(min_v)
                else:
                    return "ERR RANGE low"
            if max_v is not None and value > float(max_v):
                if command["safety"].get("clamp", True):
                    value = float(max_v)
                else:
                    return "ERR RANGE high"

    state.last_token = token
    return "OK"


def telemetry_loop(state: ClientState) -> None:
    started = time.time()
    while state.running:
        uptime_ms = int((time.time() - started) * 1000)
        try:
            send_line(state.conn, f"TELEMETRY uptime_ms={uptime_ms} last_token={state.last_token}")
        except OSError:
            break
        time.sleep(1.0)


def client_loop(conn: socket.socket, addr) -> None:
    state = ClientState(conn)
    threading.Thread(target=telemetry_loop, args=(state,), daemon=True).start()

    try:
        with conn:
            file = conn.makefile("r", encoding="utf-8", newline="\n")
            for raw_line in file:
                line = raw_line.strip()
                if not line:
                    continue

                if line == "HELLO":
                    send_line(conn, "OK")
                elif line == "READ_MANIFEST":
                    send_line(conn, f"MANIFEST {json.dumps(MANIFEST, separators=(',', ':'))}")
                elif line == "STOP":
                    state.last_token = "STOP"
                    send_line(conn, "OK")
                elif line.startswith("RUN "):
                    token, args = parse_run(line)
                    send_line(conn, handle_run(state, token, args))
                else:
                    send_line(conn, "ERR BAD_REQUEST unsupported")
    finally:
        state.running = False
        print(f"client disconnected: {addr}")


def main() -> None:
    print(f"DAEMON node emulator listening on {HOST}:{PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(5)
        while True:
            conn, addr = server.accept()
            print(f"client connected: {addr}")
            threading.Thread(target=client_loop, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
