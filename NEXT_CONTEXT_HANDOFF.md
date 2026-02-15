# Handoff / Debug Summary

## Current status
- `move in a square` now executes end-to-end from `Send` and is no longer stuck on first step.
- Remaining failures: `move left`, `move right`, `move back` (intermittent/phrase-dependent).
- SSH direct serial test (`mecanum_test.py`) works, so firmware/serial path is mostly fine.
- This points to **NL parse / plan generation / token mapping** layer, not raw motor control.

## Most likely gap
- `vision_step` parser/planner currently has explicit motion-pattern support for `forward/backward/circle/square/triangle`.
- “left/right” natural language is likely not mapped to a motion macro (`STRAFE` or `TURN`) consistently.
- “move back” may still fall into non-motion parse in some phrasings.

## Files to inspect first (root-cause)
1. `logs/vision_trace.jsonl`  
   Check `parsed_instruction.task_type`, `pattern`, `policy_branch`, generated `plan`.
2. `logs/orchestrator_trace.jsonl`  
   Check what plan was actually sent to orchestrator (`RUN` tokens + args + duration).
3. `logs/backend_audit.jsonl`  
   Ground truth HTTP payloads to `/execute_plan`.
4. `daemon-cli/firmware-code/profiles/rc_car_pi_arduino/raspberry_pi/.daemon_logs/orchestrator.log`  
   Execution-side errors/timeouts/reconnects.
5. `daemon-cli/firmware-code/profiles/rc_car_pi_arduino/raspberry_pi/.daemon_logs/vercel_api.log`  
   API runtime mismatches / stale build symptoms.
6. On Pi itself (important): `~/mecanum_node.log` or `systemctl status daemon-mecanum.service`  
   Confirms node received `RUN` tokens and mapped them.

## Code files to patch for left/right/back
1. `vercel-api/src/lib/visionPolicy.ts`  
   Extend `parseInstruction` synonyms for:
   - `move left/right` (decide strafe vs turn)
   - all back variants (`back`, `backward`, `reverse`, `go back`)
2. `vercel-api/src/app/api/vision_step/route.ts`  
   In `buildMotionSteps`, map:
   - left/right intents to `STRAFE L/R` or `TURN +/-deg`
   - backward intent to `BWD` reliably
3. `daemon-cli/firmware-code/profiles/rc_car_pi_arduino/raspberry_pi/mecanum_daemon_node.py`  
   Verify handlers for `BWD`, `STRAFE`, `TURN` parse args exactly as planner emits.
4. `vercel-api/tests/vision-policy.test.ts` + `vercel-api/tests/vision-step.test.ts`  
   Add regression tests for phrases:
   - “move left”
   - “move right”
   - “move back”
   - “go backward a bit”

## Fast log queries to run
```bash
cd /Users/vedpanse/Daemon
rg -n "applied_instruction|parsed_instruction|policy_branch|planLength|\"token\"" logs/vision_trace.jsonl -S | tail -n 80
rg -n "orchestrator.execute_plan.request|\"token\"" logs/orchestrator_trace.jsonl -S | tail -n 80
rg -n "/execute_plan|\"plan\"" logs/backend_audit.jsonl -S | tail -n 80
```

If those show wrong parse (e.g., `task_type: "unknown"`), fix is in `visionPolicy.ts`.  
If parse is correct but token wrong, fix is in `buildMotionSteps` in `route.ts`.  
If token is correct but robot doesn’t move, fix is in Pi node mapping/logs.
