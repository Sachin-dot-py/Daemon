# Arduino Integration Guide

## Inputs
- Firmware sketch with DAEMON annotations.
- `daemon-cli` installed locally.

## Steps
1. Run:
```bash
daemon build --firmware-dir /path/to/arduino/sketch
```
2. Add generated files to the Arduino project:
- `generated/daemon_entry.c`
- `generated/daemon_runtime.c`
- `generated/daemon_runtime.h`
3. In sketch code:
- call `daemon_runtime_init()` in setup
- pass received serial lines to `daemon_runtime_handle_line(line, now_ms)`
- call `daemon_runtime_tick(now_ms)` in loop
4. Keep command handlers (`function=<name>`) in sketch code.

See `examples/real_firmware_arduino/` for a complete minimal example.
