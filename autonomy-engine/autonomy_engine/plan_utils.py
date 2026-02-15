from __future__ import annotations

from typing import Any


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def _as_float(v: Any, default: float) -> float:
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return float(v)
    return default


def choose_arg_values(
    command_spec: dict[str, Any],
    policy_params: dict[str, float],
    *,
    direction_hint: str | None = None,
) -> list[Any]:
    args_spec = command_spec.get("args") if isinstance(command_spec.get("args"), list) else []
    out: list[Any] = []
    for arg in args_spec:
        if not isinstance(arg, dict):
            out.append(0)
            continue
        name = str(arg.get("name") or "").lower()
        arg_type = str(arg.get("type") or "").lower()
        enum = arg.get("enum") if isinstance(arg.get("enum"), list) else None
        min_v = arg.get("min")
        max_v = arg.get("max")

        if arg_type in {"float", "int"}:
            if "speed" in name or "throttle" in name or "power" in name:
                speed = _as_float(policy_params.get("default_speed"), 0.5)
                if min_v is not None and max_v is not None:
                    speed = _clamp(speed, float(min_v), float(max_v))
                out.append(int(speed) if arg_type == "int" else float(speed))
                continue

            if "degree" in name or name in {"deg", "degrees", "angle"}:
                mag = _as_float(policy_params.get("default_turn_degrees"), 12.0)
                sign = 1.0
                if direction_hint in {"left", "L"}:
                    sign = -1.0
                if direction_hint in {"right", "R"}:
                    sign = 1.0
                value = float(mag) * sign
                if min_v is not None and max_v is not None:
                    value = _clamp(value, float(min_v), float(max_v))
                out.append(int(value) if arg_type == "int" else float(value))
                continue

            # Default numeric: midpoint.
            if min_v is not None and max_v is not None:
                mid = (float(min_v) + float(max_v)) / 2.0
                out.append(int(mid) if arg_type == "int" else float(mid))
            else:
                out.append(0 if arg_type == "int" else 0.0)
            continue

        if arg_type == "bool":
            out.append(True)
            continue

        if arg_type == "string":
            if enum:
                # Direction hints for enum args (e.g. STRAFE dir in {L,R}).
                if direction_hint in {"L", "R"} and direction_hint in [str(v) for v in enum]:
                    out.append(direction_hint)
                    continue
                if direction_hint in {"left", "right"}:
                    want = "L" if direction_hint == "left" else "R"
                    if want in [str(v) for v in enum]:
                        out.append(want)
                        continue
                out.append(str(enum[0]))
            else:
                out.append("default")
            continue

        # Unknown types: provide placeholder.
        out.append(0)
    return out

