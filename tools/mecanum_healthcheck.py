#!/usr/bin/env python3
"""
Mecanum (Pi + Arduino) health checker.

Checks (default):
  - DNS resolution for host (shows all IPs)
  - TCP bridge connect + safe command roundtrip (S, duration 0)

Optional checks:
  - SSH into Pi (password or key) to verify:
    - /dev/ttyACM* /dev/ttyUSB* presence
    - bridge process running
    - tail bridge log

Usage examples:
  python3 tools/mecanum_healthcheck.py --host vporto26.local --port 8765 --token treehacks
  python3 tools/mecanum_healthcheck.py --host 172.20.10.7 --port 8765 --token treehacks
  python3 tools/mecanum_healthcheck.py --host vporto26.local --ssh --ssh-user treehacks --ssh-pass treehacks

Exit codes:
  0: OK
  2: Bridge/DNS failure
  3: Bridge reachable but command rejected (usually serial missing)
  4: SSH diagnostics failed (only when --ssh is provided)
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def resolve_host(host: str, port: int) -> list[Tuple[int, Tuple]]:
    # Returns list of (family, sockaddr)
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addrs: list[Tuple[int, Tuple]] = []
    for fam, _stype, _proto, _canon, sa in infos:
        if (fam, sa) not in addrs:
            addrs.append((fam, sa))
    return addrs


@dataclass
class BridgeResult:
    ok: bool
    error: Optional[str]
    raw: str


def bridge_roundtrip(host: str, port: int, token: str, cmd: str, duration_ms: int, timeout_s: float) -> BridgeResult:
    payload = {"token": token, "cmd": cmd, "duration_ms": duration_ms}
    wire = (json.dumps(payload) + "\n").encode("utf-8")

    s = socket.create_connection((host, port), timeout=timeout_s)
    try:
        s.settimeout(timeout_s)
        s.sendall(wire)

        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                return BridgeResult(False, "bridge closed connection", raw=buf.decode("utf-8", "replace"))
            buf += chunk

        line = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
        try:
            resp = json.loads(line)
        except Exception:
            return BridgeResult(False, "invalid JSON response from bridge", raw=line)

        if resp.get("ok") is True:
            return BridgeResult(True, None, raw=line)
        return BridgeResult(False, str(resp.get("error") or "bridge rejected command"), raw=line)
    finally:
        try:
            s.close()
        except Exception:
            pass


def run_ssh(user: str, host: str, password: str | None, remote_cmd: str, timeout_s: int) -> subprocess.CompletedProcess:
    base = [
        "ssh",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ServerAliveInterval=2",
        "-o",
        "ServerAliveCountMax=2",
    ]
    if password:
        base = [
            "sshpass",
            "-p",
            password,
            "ssh",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
        ] + base[1:]

    return subprocess.run(
        base + [f"{user}@{host}", remote_cmd],
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="vporto26.local")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default="treehacks")
    ap.add_argument("--timeout", type=float, default=3.0, help="TCP connect/read timeout seconds")
    ap.add_argument("--ssh", action="store_true", help="Run SSH diagnostics on the Pi")
    ap.add_argument("--ssh-user", default="treehacks")
    ap.add_argument("--ssh-pass", default="", help="If provided, uses sshpass; otherwise uses normal ssh")
    ap.add_argument("--ssh-timeout", type=int, default=12)
    args = ap.parse_args()

    host = args.host
    port = args.port
    token = args.token

    print(f"** Resolve **")
    try:
        addrs = resolve_host(host, port)
        for fam, sa in addrs:
            fam_name = "IPv6" if fam == socket.AF_INET6 else "IPv4" if fam == socket.AF_INET else str(fam)
            print(f"- {fam_name}: {sa}")
    except Exception as e:
        eprint(f"Resolution failed for {host}:{port}: {e}")
        return 2

    print(f"\n** Bridge Roundtrip (safe STOP) **")
    try:
        t0 = time.time()
        result = bridge_roundtrip(host, port, token, "S", 0, timeout_s=args.timeout)
        dt = (time.time() - t0) * 1000
        print(f"- latency_ms: {dt:.1f}")
        print(f"- raw: {result.raw}")
        if not result.ok:
            eprint(f"Bridge command failed: {result.error}")
            # If bridge exists but serial is missing, you usually get a bridge-level error here.
            return 3
        print("Bridge OK.")
    except Exception as e:
        eprint(f"Bridge connect/roundtrip failed: {e}")
        return 2

    if args.ssh:
        print(f"\n** SSH Diagnostics **")
        pw = args.ssh_pass.strip() or None
        cmd = (
            "set -e; "
            "echo 'whoami:'; whoami; "
            "echo 'dev:'; ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || true; "
            "echo 'by-id:'; ls -l /dev/serial/by-id 2>/dev/null || true; "
            "echo 'bridge proc:'; pgrep -af mecanum_bridge_server.py || echo 'no bridge'; "
            "echo 'bridge log tail:'; tail -n 30 ~/mecanum_bridge.log 2>/dev/null || true"
        )
        try:
            proc = run_ssh(args.ssh_user, host, pw, cmd, timeout_s=args.ssh_timeout)
        except Exception as e:
            eprint(f"SSH diagnostics failed: {e}")
            return 4

        if proc.returncode != 0:
            eprint("SSH command failed.")
            eprint(proc.stderr.strip() or proc.stdout.strip())
            return 4

        print(proc.stdout.strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

