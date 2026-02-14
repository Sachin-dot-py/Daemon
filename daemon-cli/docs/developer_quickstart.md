# Firmware Developer Quickstart

## 1) Install `daemon-cli` locally
Use a virtual environment or pipx (recommended for PEP-668 Homebrew Python environments).

```bash
cd daemon-cli
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m pip install -e .
```

## 2) Annotate firmware commands
Use explicit function mapping:

```c
// @daemon:export token=FWD desc="Move forward" args="speed:float[0..1]" safety="rate_hz=10,watchdog_ms=500,clamp=true" function=drive_fwd
```

`function=<name>` is required.

## 3) Generate runtime artifacts
```bash
daemon build --firmware-dir /path/to/firmware
```

## 4) Integrate generated files
Follow generated `DAEMON_INTEGRATION.md`:
- Add generated C files to your build.
- Call runtime init in startup.
- Route incoming serial lines into runtime handler.
- Tick runtime in main loop.

## 5) Run locally with emulator + orchestrator
No cloud is required.
- Start one or more DAEMON nodes (real firmware or emulator).
- Start orchestrator with `--node alias=host:port` entries.
- Run local fallback planner when no planner URL is set.
