# Multi-Manufacturer Composition

## Runtime model
- Manufacturer A (robot base) runs `daemon build` in their own firmware repo and ships a DAEMON node.
- Manufacturer B (arm) does the same in a separate firmware repo.
- End user plugs both devices in and runs orchestrator with both node endpoints.

## Composition
- Orchestrator reads each node manifest at runtime.
- It fuses capabilities into a single command catalog.
- Planner output references node `target` plus token.
- If a token collides across nodes, plan must use explicit target.

## What is not required
- No firmware merging across manufacturers.
- No shared monolithic binary.
- No cloud dependency for local orchestration and fallback planning.
