# EXECUTIVE.md

# DAEMON

### AI-Native Firmware-to-Agent Bridge

---

# 1. What Daemon Is

Daemon is a distributed embodiment protocol that enables AI systems to control microcontroller-based hardware **without custom per-device integration**.

Each hardware component (robot base, robotic arm, etc.) runs its own firmware.
Daemon generates a structured, safe control interface on top of that firmware.

At runtime:

* Devices expose a **Manifest**
* An **Orchestrator** fuses multiple devices into a unified “body”
* A **Planner (Vercel-hosted)** converts natural language into structured execution plans
* The Orchestrator validates and executes those plans safely

Daemon does **not** merge firmware.
It composes devices via capability manifests.

---

# 2. Repository Structure (Monorepo)

```
/
├── daemon-cli/        # Developer tool: ./daemon build + emulator + schema
├── orchestrator/      # Runtime system: multi-node composition + plan execution
├── vercel-api/        # Planner API (hosted on Vercel)
├── desktop-app/       # Thin client (UI layer) – NOT core runtime
└── EXECUTIVE.md
```

### Ownership

* Ved → `daemon-cli/` + `orchestrator/`
* Sachin → `vercel-api/`
* `desktop-app/` is thin UI and not core architecture

---

# 3. System Architecture

## 3.1 Components

### A) Daemon Node (runs on hardware)

Each firmware repo runs:

```
./daemon build
```

Which generates:

* `DAEMON.yml` (manifest)
* `daemon_entry.c` (command dispatcher)
* `daemon_runtime.c/h` (protocol + safety layer)

Each device becomes a **Daemon Node**.

---

### B) Wire Protocol (serial-line-v1)

Host → Device:

```
HELLO
READ_MANIFEST
RUN <TOKEN> <args...>
STOP
SUB TELEMETRY
UNSUB TELEMETRY
```

Device → Host:

```
MANIFEST <json>
OK
ERR <code> <message>
TELEMETRY key=value ...
```

Telemetry is opt-in (no unsolicited output before SUB).

---

### C) Orchestrator

* Connects to multiple nodes
* Fetches MANIFEST from each
* Builds a unified capability graph
* Routes commands to correct node
* Validates planner output
* Enforces safety (timeouts, STOP, panic stop)

Supports:

* Multi-node composition
* Planner fallback if remote fails
* Emergency STOP on Ctrl+C

---

### D) Planner (Vercel API)

Endpoint:

```
POST /api/plan
```

Input:

```
{
  instruction,
  system_manifest,
  telemetry_snapshot
}
```

Output:

```
{
  plan: [
    { type: "RUN", target, token, args, duration_ms? },
    { type: "STOP" }
  ],
  explanation
}
```

Planner never touches hardware directly.

---

# 4. Manifest Schema (v0.1)

Each node exposes:

```
daemon_version: "0.1"
device:
  name
  version
  node_id

commands:
  - token
  - description
  - args:
      - name
      - type (int|float|bool|string)
      - min
      - max
      - required
  - safety:
      rate_limit_hz
      watchdog_ms
      clamp
  - nlp:
      synonyms
      examples

telemetry:
  keys:
    - name
    - type
    - unit (optional)

transport:
  type: "serial-line-v1"
```

---

# 5. Current Working Demo

## Nodes

* Base robot (FWD, TURN)
* Arm (ARM_TO, GRIP, HOME)

## Flow

1. Start base + arm emulators
2. Start orchestrator
3. Orchestrator fetches manifests
4. User types:

   ```
   forward then close gripper
   ```
5. Planner returns structured plan
6. Orchestrator validates + executes
7. STOP sent globally

Working features:

* Multi-node routing
* Strict plan validation
* Emergency stop
* Telemetry streaming
* Planner fallback mode

---

# 6. Safety Model

Layered safety:

### Device-level

* Arg clamping
* Rate limits
* Watchdog timeout
* STOP always available

### Orchestrator-level

* Plan validation against manifest
* Per-step timeout
* Panic STOP on failure
* Ctrl+C sends STOP to all nodes

### Planner-level

* Must only use manifest-exposed tokens
* Must respect arg ranges

---

# 7. Multi-Manufacturer Model

Manufacturer A:

* Ships robot base firmware
* Runs `daemon build`
* Ships Daemon Node

Manufacturer B:

* Ships robotic arm firmware
* Runs `daemon build`
* Ships Daemon Node

User:

* Connects both
* Orchestrator fuses manifests
* Planner returns cross-device plan

No firmware merging required.

---

# 8. NLP Macros (Current Behavior)

Planner and/or local fallback supports:

* "forward"
* "turn left"
* "close gripper"
* "square" → compiled into 4x FWD + TURN
* "triangle"
* "straight line"

Current implementation is time-based (open-loop).

Closed-loop accuracy requires:

* Encoders
* IMU feedback
* More advanced control primitives

---

# 9. What Is Completed

✔ `daemon-cli` build tool
✔ Manifest generation
✔ Emulator
✔ Orchestrator multi-node routing
✔ Planner API integration
✔ Strict validation + STOP safety
✔ Demo works end-to-end

---

# 10. Known Limitations

* Open-loop movement (time-based)
* No real hardware demo yet (emulator-based)
* Desktop app is thin UI, not deeply integrated
* Planner is rule-based MVP

---

# 11. Next Major Milestones

### Short-Term

* Run on real microcontroller firmware
* Add at least one real hardware proof
* Clean install experience (`pipx` / packaged CLI)

### Mid-Term

* Closed-loop motion primitives
* Richer capability graph
* Persistent learning of embodiment
* Skill composition

### Long-Term

* AI-native robotics abstraction layer
* Hardware marketplace compatibility
* Industrial automation integration
* Research-grade embodied AI runtime

---

# 12. Core Philosophy

The internet standardized information exchange.

Daemon standardizes embodiment exchange.

It enables AI systems to inhabit physical systems safely and compositionally.

---

# 13. Demo Script (60 seconds)

1. Start base node
2. Start arm node
3. Start orchestrator
4. Type:

   ```
   forward then close gripper
   ```
5. Show structured plan
6. Show execution
7. Kill arm node
8. Try “close gripper” → fails
9. Restart arm node
10. Try again → works

Message:

> “We didn’t hardcode the arm. The system discovered capabilities at runtime.”