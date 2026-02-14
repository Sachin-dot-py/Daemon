# Manifest Schema v0.1

Schema file: `daemon-cli/schema/daemon.schema.v0_1.json`

## Top-level
- `daemon_version` (required string, current `"0.1"`)
- `device` (required object)
- `commands` (required array)
- `telemetry` (required object)
- `transport` (required object)

## `device`
- `name` (required string)
- `version` (required string)
- `node_id` (required string, stable node identity)
- `manufacturer` (optional string)

## `commands[]`
- `token` (required short string, `[A-Z0-9_]+`, max 32 chars)
- `description` (required string)
- `args[]` where each arg has:
  - `name` (required)
  - `type` in `{int,float,bool,string}`
  - `required` (bool)
  - `min`/`max` (optional numeric bounds for numeric args)
- `safety` with `rate_limit_hz`, `watchdog_ms`, `clamp`
- `nlp` with `synonyms[]`, `examples[]`

## `telemetry`
- `keys[]` entries with `name`, `type`, optional `unit`

## `transport`
- `type` must be `serial-line-v1`

## Token/namespace rules
- Tokens are local to a node manifest.
- In multi-node orchestration, collisions are allowed across nodes.
- Unqualified tokens are valid only when globally unique.
- Colliding tokens require explicit target (for example `base.SET` vs `arm.SET`).
