# DAEMON Vercel API

This project is the deploy target for DAEMON cloud endpoints. It includes:
- `POST /api/plan` and `POST /plan` for orchestrator planning
- `POST /api/v1/daemon-configs/ingest` for CLI publish ingest
- `POST /api/realtime/evaluate` for desktop realtime hardware validation loop
- `GET /api/health` for service health checks

## Run locally

```bash
npm install
npm run dev
```

Local base URL: `http://localhost:3000`

## Environment variables

All are optional for MVP:

- `DAEMON_PUBLISH_API_KEY`
  - If set, `POST /api/v1/daemon-configs/ingest` requires:
  - `Authorization: Bearer <DAEMON_PUBLISH_API_KEY>`
- `BLOB_READ_WRITE_TOKEN`
  - If set, ingest artifacts are persisted to Vercel Blob
  - If missing, ingest still returns success without persistence
- `OPENAI_API_KEY`
  - Optional: if set, realtime evaluator can use OpenAI multimodal analysis (webcam frame + telemetry + audio level)
  - If missing, evaluator uses built-in heuristic fallback
- `OPENAI_REALTIME_REVIEW_MODEL`
  - Optional: override model name for realtime evaluator (default `gpt-4o-mini`)

## Planner endpoint

- `POST /api/plan`
- `POST /plan` (rewrite to `/api/plan`)

## Example request

```bash
curl -X POST http://localhost:3000/api/plan \
  -H "Content-Type: application/json" \
  -d '{
    "instruction": "forward then close gripper",
    "system_manifest": {
      "daemon_version": "0.1",
      "nodes": [
        {
          "name": "base",
          "node_id": "node-base-1",
          "commands": [
            { "token": "FWD", "args": [{ "type": "number", "min": 0, "max": 1 }] },
            { "token": "BWD", "args": [{ "type": "number", "min": 0, "max": 1 }] },
            { "token": "TURN", "args": [{ "type": "number", "min": -180, "max": 180 }] },
            { "token": "L", "args": [{ "type": "number", "min": 0, "max": 1000 }] }
          ],
          "telemetry": {}
        },
        {
          "name": "arm",
          "node_id": "node-arm-1",
          "commands": [
            { "token": "GRIP", "args": [{ "type": "string", "enum": ["open", "close"] }] },
            { "token": "HOME", "args": [] }
          ],
          "telemetry": {}
        }
      ]
    },
    "telemetry_snapshot": {
      "base": { "uptime_ms": 123, "last_token": "NONE" },
      "arm": { "uptime_ms": 456, "last_token": "NONE" }
    }
  }'
```

## Example success response

```json
{
  "plan": [
    { "type": "RUN", "target": "base", "token": "FWD", "args": [0.6], "duration_ms": 1200 },
    { "type": "RUN", "target": "arm", "token": "GRIP", "args": ["close"] },
    { "type": "STOP" }
  ],
  "explanation": "Move forward, then close gripper, then stop."
}
```

## Validation failure shape

```json
{
  "error": "VALIDATION_ERROR",
  "message": "RUN step token does not exist in target node command catalog.",
  "details": {}
}
```

## CLI ingest endpoint

- `POST /api/v1/daemon-configs/ingest`
- `GET /api/health`

Example health check:

```bash
curl http://localhost:3000/api/health
```

Example ingest request:

```bash
curl -X POST http://localhost:3000/api/v1/daemon-configs/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "config_id": "rc_car_pi_arduino",
    "manifest": { "profile": "rc_car_pi_arduino", "version": "0.1" },
    "artifacts": {
      "DAEMON.yaml": "name: rc_car_pi_arduino\n",
      "daemon_entry.c": "int main(void){return 0;}\n"
    }
  }'
```

If auth is enabled:

```bash
curl -X POST http://localhost:3000/api/v1/daemon-configs/ingest \
  -H "Authorization: Bearer $DAEMON_PUBLISH_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ ... }'
```

## Realtime evaluator endpoint

- `POST /api/realtime/evaluate`
- Supports `event` values: `start`, `observe`, `stop`
- CORS headers are enabled for desktop-origin requests

Example `start` request:

```bash
curl -X POST http://localhost:3000/api/realtime/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "event": "start",
    "expected_outcome": "Robot moves forward and stops",
    "current_code": "RUN FWD 0.6\nSTOP",
    "telemetry_tail": ["speed=0.0"]
  }'
```

Example `observe` request:

```bash
curl -X POST http://localhost:3000/api/realtime/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "event": "observe",
    "session_id": "SESSION_ID_FROM_START",
    "expected_outcome": "Robot moves forward and stops",
    "current_code": "RUN FWD 0.6\nSTOP",
    "telemetry_tail": ["RUN FWD", "speed=0.4"],
    "observation": {
      "timestamp_ms": 1739500000000,
      "audio_rms": 0.023,
      "video_frame_jpeg_base64": "..."
    }
  }'
```

Example success response:

```json
{
  "session_id": "13a8f903-f7cb-497f-aab6-2754ffbc4f0c",
  "status": "MONITORING",
  "decision": "MISMATCH",
  "confidence": 0.72,
  "message": "Expected device motion was not visible from recent observations.",
  "should_update_code": true,
  "updated_code": "RUN FWD 0.69\nSTOP",
  "patch_summary": "Adjusted control value 60 -> 69 based on observed behavior."
}
```

## Vercel deployment

Set Vercel project root directory to `vercel-api`.
