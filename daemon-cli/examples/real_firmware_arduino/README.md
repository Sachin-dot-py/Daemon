# Real Firmware Arduino Example

This is a minimal local-only example showing how `daemon build` integrates with real firmware source.

## What it exports
- `FWD(speed: float[0..1])` via `drive_fwd`
- `TURN(deg: float[-180..180])` via `turn_deg`

Both exports use explicit mapping with `function=<firmware_function_name>`.

## Generate DAEMON artifacts
From this folder:

```bash
cd daemon-cli/examples/real_firmware_arduino
../../daemon build --firmware-dir .
```

Generated files:
- `generated/DAEMON.yml`
- `generated/daemon_entry.c`
- `generated/daemon_runtime.c`
- `generated/daemon_runtime.h`
- `generated/DAEMON_INTEGRATION.md`

## Arduino integration
1. Keep `firmware.ino` in your sketch.
2. Add `generated/daemon_entry.c` and `generated/daemon_runtime.c` to the Arduino project sources.
3. Keep `#include "generated/daemon_runtime.h"` in `firmware.ino`.
4. Keep `daemon_init()` in `setup()` and `daemon_loop(millis())` in `loop()`.

This example is intentionally open-loop and demo-oriented. For accurate motion on hardware, add feedback sensors (encoders/IMU) and closed-loop control in `drive_fwd`/`turn_deg`.
