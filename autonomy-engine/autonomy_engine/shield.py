from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .manifest import get_command_spec
from .plan_utils import choose_arg_values
from .semantics import CapabilityMapping
from .taskspec import TaskSpec
from .tracker import BBox, TrackerOutput


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def _center(rect: dict[str, float]) -> tuple[float, float]:
    return (rect["x"] + rect["w"] / 2.0, rect["y"] + rect["h"] / 2.0)


def _contains(outer: dict[str, float], inner: BBox) -> bool:
    return (
        inner.x >= outer["x"]
        and inner.y >= outer["y"]
        and (inner.x + inner.w) <= (outer["x"] + outer["w"])
        and (inner.y + inner.h) <= (outer["y"] + outer["h"])
    )


@dataclass(frozen=True)
class ShieldDecision:
    overridden: bool
    reason: str
    plan: list[dict[str, Any]]


def home_ok(bbox: BBox | None, spec: TaskSpec) -> bool:
    if bbox is None:
        return False
    return _contains(spec.home_roi, bbox)


def maybe_override(
    *,
    tracker: TrackerOutput,
    spec: TaskSpec,
    caps: CapabilityMapping,
    system_manifest: dict[str, Any],
) -> ShieldDecision | None:
    """
    Return a shield override plan when unsafe/offscreen, otherwise None.
    """
    visible_min = float(spec.safety.get("visible_conf_min", 0.12))
    margin_min = float(spec.policy_params.get("center_margin", 0.12))
    max_step_ms = float(spec.safety.get("max_step_ms", 800))

    bbox = tracker.bbox
    if bbox is None or tracker.visibility_confidence < visible_min:
        return ShieldDecision(overridden=True, reason="not_visible", plan=[{"type": "STOP"}])

    # If bbox is outside ROI, stop.
    if not _contains(spec.camera_roi, bbox):
        return ShieldDecision(overridden=True, reason="outside_roi", plan=[{"type": "STOP"}])

    # If near the ROI edge, try to steer toward home center.
    if tracker.edge_margin < margin_min:
        if not caps.mobility_target:
            return ShieldDecision(overridden=True, reason="edge_no_mobility", plan=[{"type": "STOP"}])

        desired_x, _desired_y = _center(spec.home_roi)
        cx, _cy = bbox.center()
        dir_lr = "left" if cx > desired_x else "right"

        # Prefer strafe when available, otherwise turn.
        if caps.strafe_token:
            token = caps.strafe_token
            cmd = get_command_spec(system_manifest, caps.mobility_target, token)
            if not cmd:
                return ShieldDecision(overridden=True, reason="edge_strafe_missing_spec", plan=[{"type": "STOP"}])
            args = choose_arg_values(cmd, spec.policy_params, direction_hint="L" if dir_lr == "left" else "R")
            duration = _clamp(float(spec.policy_params.get("strafe_duration_ms", 220.0)), 80.0, max_step_ms)
            return ShieldDecision(
                overridden=True,
                reason=f"edge_strafe_{dir_lr}",
                plan=[{"type": "RUN", "target": caps.mobility_target, "token": token, "args": args, "duration_ms": duration}, {"type": "STOP"}],
            )

        if caps.turn_token:
            token = caps.turn_token
            cmd = get_command_spec(system_manifest, caps.mobility_target, token)
            if not cmd:
                return ShieldDecision(overridden=True, reason="edge_turn_missing_spec", plan=[{"type": "STOP"}])
            args = choose_arg_values(cmd, spec.policy_params, direction_hint=dir_lr)
            duration = _clamp(float(spec.policy_params.get("turn_duration_ms", 220.0)), 80.0, max_step_ms)
            return ShieldDecision(
                overridden=True,
                reason=f"edge_turn_{dir_lr}",
                plan=[{"type": "RUN", "target": caps.mobility_target, "token": token, "args": args, "duration_ms": duration}, {"type": "STOP"}],
            )

        return ShieldDecision(overridden=True, reason="edge_no_motion_tokens", plan=[{"type": "STOP"}])

    return None

