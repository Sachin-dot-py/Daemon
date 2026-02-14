# DAEMON CLI

CLI and code generation for `daemon build`.
This package is a firmware developer tool and does not require OpenAI.

## Install
Homebrew-managed Python environments may enforce PEP 668 and block system-wide `pip install`. Use one of these local install modes.

### Option 1: `venv` (recommended)
```bash
cd daemon-cli
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m pip install -e .
```

### Option 2: `pipx` (CLI-focused)
```bash
brew install pipx
pipx ensurepath
cd daemon-cli
pipx install -e .
```

## Command
```bash
daemon build --firmware-dir /path/to/firmware
```

Generated files:
- `generated/DAEMON.yml`
- `generated/daemon_entry.c`
- `generated/daemon_runtime.c`
- `generated/daemon_runtime.h`
- `generated/DAEMON_INTEGRATION.md`

## Annotation format
```c
// @daemon:export token=FWD desc="Move forward" args="speed:float[0..1]" safety="rate_hz=10,watchdog_ms=500,clamp=true" function=drive_fwd
```

`function=<name>` is required. If missing, build fails with `export requires function=<name>`.

## Docs
- `docs/protocol.md` (`serial-line-v1` wire protocol)
- `docs/manifest_schema.md` (manifest schema v0.1)
- `docs/developer_quickstart.md`
- `docs/arduino_integration.md`
- `docs/cmake_make_integration.md`
- `docs/manufacturers.md`

## Local demo flow (no cloud required)
1. Start two emulators:
```bash
cd daemon-cli
./examples/run_two_nodes.sh
```
2. Run orchestrator locally without planner URL:
```bash
python ../orchestrator/orchestrator.py --node base=localhost:7777 --node arm=localhost:7778
```

## Acceptance checklist commands
1. Install daemon-cli (venv):
```bash
cd daemon-cli
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m pip install -e .
```
2. Start base + arm emulators with YAML manifests:
```bash
python3 daemon-cli/examples/node-emulator/emulator.py --port 7777 --manifest daemon-cli/examples/manifests/base.yml
python3 daemon-cli/examples/node-emulator/emulator.py --port 7778 --manifest daemon-cli/examples/manifests/arm.yml
```
3. Run orchestrator with planner URL and execute `forward then close gripper`, then `square`:
```bash
python3 orchestrator/orchestrator.py --node base=localhost:7777 --node arm=localhost:7778 --planner-url https://<domain>/api/plan
```
4. Run orchestrator without planner URL and execute `square`:
```bash
python3 orchestrator/orchestrator.py --node base=localhost:7777 --node arm=localhost:7778
```
5. Show collision requiring explicit target:
```bash
python3 daemon-cli/examples/node-emulator/emulator.py --port 7781 --manifest daemon-cli/examples/manifests/collision.yml
python3 daemon-cli/examples/node-emulator/emulator.py --port 7782 --manifest daemon-cli/examples/manifests/collision.yml
python3 orchestrator/orchestrator.py --node base=localhost:7781 --node arm=localhost:7782
```
Then in REPL:
- `RUN SET ...` style unqualified planning is ambiguous and requires target.
- Use explicit targets in plan (`target: "base"` or `target: "arm"`).

## Tests
```bash
cd daemon-cli
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

## Smoke test
```bash
bash daemon-cli/tools/smoke_test.sh
```
