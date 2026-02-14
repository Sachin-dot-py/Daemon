#!/usr/bin/env python3
"""
Tiny TCP -> serial bridge for the mecanum Arduino sketch.

Protocol (one JSON per line):
  {"token":"<optional>","cmd":"F","duration_ms":500}

Response (one JSON per line):
  {"ok":true,"cmd":"F","duration_ms":500}
  {"ok":false,"error":"..."}
"""

import argparse
import json
import socket
import threading
import time

import serial  # pyserial
from serial.serialutil import SerialException


ALLOWED_CMDS = {"F", "B", "L", "R", "Q", "E", "S"}


class SerialBridge:
    def __init__(self, port: str, baud: int):
        self._port = port
        self._baud = baud
        self._lock = threading.Lock()
        self._ser = None

    def _open_serial(self):
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

        # May raise SerialException if the device is unplugged / path is wrong.
        self._ser = serial.Serial(self._port, self._baud, timeout=1)
        # Most Arduinos reset on open; give it time to boot.
        time.sleep(2.0)

    def dispatch(self, cmd: str, duration_ms: int):
        if cmd not in ALLOWED_CMDS:
            raise ValueError("unsupported cmd")
        if duration_ms < 0 or duration_ms > 10000:
            raise ValueError("duration_ms out of range")

        with self._lock:
            try:
                if not self._ser or not self._ser.is_open:
                    self._open_serial()

                self._ser.write(cmd.encode("ascii"))
                self._ser.flush()
                if cmd != "S" and duration_ms > 0:
                    time.sleep(duration_ms / 1000.0)
                    self._ser.write(b"S")
                    self._ser.flush()
            except Exception:
                # Attempt one reopen + retry once.
                self._open_serial()
                self._ser.write(cmd.encode("ascii"))
                self._ser.flush()
                if cmd != "S" and duration_ms > 0:
                    time.sleep(duration_ms / 1000.0)
                    self._ser.write(b"S")
                    self._ser.flush()


def handle_client(conn: socket.socket, addr, bridge: SerialBridge, token: str | None):
    # Keep connections alive across multiple commands.
    # We still use a timeout to prevent dead sockets from hanging threads forever.
    conn.settimeout(60.0)
    buf = b""
    try:
        while True:
            try:
                chunk = conn.recv(4096)
            except (socket.timeout, TimeoutError):
                # Idle connection; keep waiting.
                continue
            except (ConnectionResetError, BrokenPipeError):
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line.decode("utf-8"))
                    if token and req.get("token") != token:
                        raise ValueError("unauthorized")
                    cmd = str(req.get("cmd", "")).strip().upper()
                    duration_ms = int(req.get("duration_ms", 0))
                    bridge.dispatch(cmd, duration_ms)
                    resp = {"ok": True, "cmd": cmd, "duration_ms": duration_ms}
                except Exception as e:
                    resp = {"ok": False, "error": str(e)}
                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    # Prefer IPv6 wildcard. On Linux this can be dual-stack if IPV6_V6ONLY=0.
    ap.add_argument("--listen", default="::")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--serial", default="/dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--token", default="")
    args = ap.parse_args()

    token = args.token.strip() or None
    bridge = SerialBridge(args.serial, args.baud)
    # Attempt initial serial open so the first command doesn't pay the reset delay.
    # If the Arduino is unplugged, keep the bridge alive and let dispatch() reopen later.
    try:
        bridge._open_serial()
    except (FileNotFoundError, SerialException) as e:
        print(f"warning: serial not ready at startup ({args.serial}): {e}", flush=True)

    # Try dual-stack IPv6 first so `.local` (often IPv6 link-local) can connect.
    srv = None
    bind_error = None
    for family, sockaddr in (
        (socket.AF_INET6, (args.listen, args.port, 0, 0)),
        (socket.AF_INET, ("0.0.0.0", args.port)),
    ):
        try:
            candidate = socket.socket(family, socket.SOCK_STREAM)
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                try:
                    candidate.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                except Exception:
                    pass
            candidate.bind(sockaddr)
            srv = candidate
            bind_error = None
            break
        except Exception as e:
            bind_error = e
            try:
                candidate.close()
            except Exception:
                pass
            continue

    if srv is None:
        raise SystemExit(f"Failed to bind bridge socket: {bind_error}")

    srv.listen(32)
    print(f"mecanum bridge listening on {args.listen}:{args.port} -> {args.serial}@{args.baud}", flush=True)

    while True:
        conn, addr = srv.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr, bridge, token), daemon=True)
        t.start()


if __name__ == "__main__":
    main()
