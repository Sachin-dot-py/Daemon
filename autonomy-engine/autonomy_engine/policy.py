from __future__ import annotations

import json
from typing import Any

from .manifest import get_command_spec
from .openai_client import openai_api_key, responses_json_schema
from .semantics import CapabilityMapping
from .taskspec import TaskSpec
from .tracker import TrackerOutput


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def _sanitize_args(
    args: list[Any],
    spec_args: list[Any],
    policy_params: dict[str, float],
) -> list[Any]:
    out: list[Any] = []
    default_speed = float(policy_params.get("default_speed", 0.5))
    default_turn_deg = float(policy_params.get("default_turn_degrees", 12.0))

    for idx, arg_spec in enumerate(spec_args):
        if idx >= len(args):
            break
        raw = args[idx]
        if not isinstance(arg_spec, dict):
            out.append(raw)
            continue
        arg_type = str(arg_spec.get("type") or "").lower()
        name = str(arg_spec.get("name") or "").lower()
        enum = arg_spec.get("enum") if isinstance(arg_spec.get("enum"), list) else None
        min_v = arg_spec.get("min")
        max_v = arg_spec.get("max")

        if arg_type in {"float", "int"}:
            if isinstance(raw, bool):
                num = 0.0
            else:
                try:
                    num = float(raw)
                except Exception:
                    num = 0.0

            if "speed" in name or "throttle" in name or "power" in name:
                if min_v is not None:
                    num = max(num, float(min_v))
                num = min(num, default_speed)
            if "degree" in name or name in {"deg", "degrees", "angle"}:
                num = _clamp(num, -abs(default_turn_deg), abs(default_turn_deg))

            if min_v is not None:
                num = max(num, float(min_v))
            if max_v is not None:
                num = min(num, float(max_v))

            out.append(int(round(num)) if arg_type == "int" else float(num))
            continue

        if arg_type == "bool":
            if isinstance(raw, bool):
                out.append(raw)
            elif isinstance(raw, str) and raw.lower() in {"true", "1"}:
                out.append(True)
            elif isinstance(raw, str) and raw.lower() in {"false", "0"}:
                out.append(False)
            else:
                out.append(False)
            continue

        if arg_type == "string":
            if enum:
                raw_s = str(raw)
                if raw_s in [str(v) for v in enum]:
                    out.append(raw_s)
                else:
                    out.append(str(enum[0]))
            else:
                out.append(str(raw))
            continue

        out.append(raw)

    return out


def _compact_manifest(system_manifest: dict[str, Any], semantics: dict[str, dict[str, Any]], *, limit_cmds: int = 60) -> dict[str, Any]:
    nodes_in = system_manifest.get("nodes") if isinstance(system_manifest.get("nodes"), list) else []
    nodes_out: list[dict[str, Any]] = []
    cmd_count = 0
    for node in nodes_in:
        if not isinstance(node, dict):
            continue
        out_node = {"name": node.get("name"), "node_id": node.get("node_id"), "commands": []}
        commands = node.get("commands") if isinstance(node.get("commands"), list) else []
        for cmd in commands:
            if not isinstance(cmd, dict):
                continue
            token = cmd.get("token")
            if not isinstance(token, str) or not token.strip():
                continue
            key = f"{out_node['node_id']}:{token.strip().upper()}"
            rec = semantics.get(key) or {}
            out_node["commands"].append(
                {
                    "token": token.strip().upper(),
                    "description": cmd.get("description"),
                    "args": cmd.get("args"),
                    "tags": rec.get("tags"),
                }
            )
            cmd_count += 1
            if cmd_count >= limit_cmds:
                break
        nodes_out.append(out_node)
        if cmd_count >= limit_cmds:
            break
    return {"daemon_version": system_manifest.get("daemon_version"), "nodes": nodes_out}


def plan_next_step_openai(
    *,
    instruction: str,
    system_manifest: dict[str, Any],
    semantics: dict[str, dict[str, Any]],
    caps: CapabilityMapping,
    tracker: TrackerOutput,
    spec: TaskSpec,
    model: str = "gpt-4.1-mini",
) -> tuple[list[dict[str, Any]], str]:
    """
    Returns (plan, reason). Plan is intended to be executed as-is by the orchestrator.
    """
    if not openai_api_key():
        return [{"type": "STOP"}], "openai_disabled_missing_api_key"

    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reason": {"type": "string"},
            "plan": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {
                    "oneOf": [
                        {"type": "object", "additionalProperties": False, "properties": {"type": {"const": "STOP"}}, "required": ["type"]},
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "type": {"const": "RUN"},
                                "target": {"type": "string"},
                                "token": {"type": "string"},
                                "args": {"type": "array"},
                                "duration_ms": {"type": "number", "minimum": 0, "maximum": float(spec.safety.get("max_step_ms", 800))},
                            },
                            "required": ["type", "target", "token", "args"],
                        },
                    ]
                },
            },
        },
        "required": ["reason", "plan"],
    }

    manifest_compact = _compact_manifest(system_manifest, semantics)
    obs = {
        "visible_conf": tracker.visibility_confidence,
        "edge_margin": tracker.edge_margin,
        "bbox": tracker.bbox.__dict__ if tracker.bbox else None,
        "mobility_target": caps.mobility_target,
        "hint": "Stay within camera ROI; if uncertain or unsafe, output STOP.",
    }

    system_text = (
        "You are a robot action selector.\n"
        "You must select ONLY from the provided DAEMON manifest commands.\n"
        "Return a short plan for the next step only (one RUN or STOP).\n"
        "Safety rules:\n"
        "- If the robot is not visible (bbox null) or edge_margin is low, prefer STOP.\n"
        "- Keep durations short.\n"
        "- If you need to move, choose locomotion-tagged commands on the mobility target when possible.\n"
        "Output strict JSON only."
    )

    user_text = {
        "instruction": instruction,
        "observation": obs,
        "system_manifest": manifest_compact,
        "policy_params": spec.policy_params,
    }

    out, _raw = responses_json_schema(
        model=model,
        schema_name="daemon_next_step_plan",
        schema=schema,
        system_text=system_text,
        user_content=[{"type": "input_text", "text": json.dumps(user_text, separators=(",", ":"))}],
        temperature=0.0,
        timeout_s=12.0,
    )

    plan = out.get("plan")
    reason = out.get("reason")
    if not isinstance(plan, list) or not isinstance(reason, str):
        return [{"type": "STOP"}], "openai_invalid_output"

    # Normalize: ensure we always end with STOP when RUN is chosen (safety).
    normalized: list[dict[str, Any]] = []
    for step in plan[:1]:
        if not isinstance(step, dict):
            continue
        st = str(step.get("type") or "").upper()
        if st == "STOP":
            normalized.append({"type": "STOP"})
        elif st == "RUN":
            normalized.append(
                {
                    "type": "RUN",
                    "target": str(step.get("target") or ""),
                    "token": str(step.get("token") or "").upper(),
                    "args": step.get("args") if isinstance(step.get("args"), list) else [],
                    **({"duration_ms": float(step["duration_ms"])} if isinstance(step.get("duration_ms"), (int, float)) else {}),
                }
            )

    if not normalized:
        return [{"type": "STOP"}], "openai_empty_plan"

    if normalized[0].get("type") == "RUN":
        # Clamp/sanitize args to reduce runtime validation failures and avoid extreme values.
        target = str(normalized[0].get("target") or "")
        token = str(normalized[0].get("token") or "").upper()
        cmd = get_command_spec(system_manifest, target, token)
        if cmd and isinstance(cmd.get("args"), list) and isinstance(normalized[0].get("args"), list):
            normalized[0]["args"] = _sanitize_args(normalized[0]["args"], cmd.get("args"), spec.policy_params)
        normalized.append({"type": "STOP"})

    return normalized, reason


def plan_next_step_fallback(*, instruction: str) -> tuple[list[dict[str, Any]], str]:
    # Conservative fallback: stop if we cannot safely reason about actions.
    if "stop" in instruction.lower():
        return [{"type": "STOP"}], "fallback_stop"
    return [{"type": "STOP"}], "fallback_noop"
