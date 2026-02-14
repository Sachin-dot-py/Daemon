# Generic CMake/Make Integration Guide

## Generate files
```bash
daemon build --firmware-dir /path/to/firmware
```

## Add to build graph
- Compile `generated/daemon_entry.c` and `generated/daemon_runtime.c`.
- Add include path for generated directory.
- Include `generated/daemon_runtime.h` from your firmware main loop.

## Runtime hooks
- Initialize with `daemon_runtime_init()`.
- On each received serial line, call `daemon_runtime_handle_line(line, now_ms)`.
- In periodic loop/timer, call `daemon_runtime_tick(now_ms)`.

## Notes
- Protocol transport is `serial-line-v1`.
- Keep STOP handling wired and idempotent.
- Closed-loop motion accuracy requires sensor feedback logic in your command handlers.
