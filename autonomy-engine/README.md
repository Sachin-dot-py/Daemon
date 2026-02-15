# Autonomy Engine (DAEMON)

Laptop-local closed-loop autonomy runner for DAEMON robots:
- Connects to the local orchestrator HTTP bridge (`/status`, `/execute_plan`, `/stop`, `/telemetry`)
- Captures webcam frames
- Infers command semantics from the DAEMON manifest (optional OpenAI assist)
- Runs an autonomous execute → judge → patch → retry loop

This is intentionally hardware-agnostic: the **manifest** is the control surface.

## Setup

From repo root:

```bash
python3 -m venv autonomy-engine/.venv
source autonomy-engine/.venv/bin/activate
python3 -m pip install -r autonomy-engine/requirements.txt
python3 -m pip install -e autonomy-engine
```

## Run

1) Start the orchestrator HTTP bridge (example):

```bash
python3 orchestrator/orchestrator.py \
  --node base=localhost:7777 \
  --node arm=localhost:7778 \
  --http-port 5055 \
  --telemetry
```

2) Run the autonomy engine:

```bash
export OPENAI_API_KEY=...
python3 autonomy-engine/run_engine.py \
  --orchestrator http://127.0.0.1:5055 \
  --camera 0 \
  --instruction "pick up the banana" \
  --attempts 10
```

Or use a taskspec file (the engine may update `policy_params` over time):

```bash
python3 autonomy-engine/run_engine.py --taskspec autonomy-engine/tasks/example.taskspec.json
```

## Notes
- Episode artifacts (frames + step logs) are written under `.daemon/episodes/` by default.
- Without a marker (AprilTag/ArUco), reliable auto-reset requires a **physical arena** that keeps the robot in view.
- If `OPENAI_API_KEY` is missing, the engine can still execute plans but judge/planner features will be disabled.
