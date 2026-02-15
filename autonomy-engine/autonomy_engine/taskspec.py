from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def _as_norm_rect(value: Any, default: dict[str, float]) -> dict[str, float]:
    if not isinstance(value, dict):
        return dict(default)
    out = {}
    for k in ("x", "y", "w", "h"):
        raw = value.get(k)
        if not isinstance(raw, (int, float)):
            return dict(default)
        out[k] = float(raw)
    # Clamp to [0,1]
    x = _clamp(out["x"], 0.0, 1.0)
    y = _clamp(out["y"], 0.0, 1.0)
    w = _clamp(out["w"], 0.0, 1.0 - x)
    h = _clamp(out["h"], 0.0, 1.0 - y)
    if w <= 0.0 or h <= 0.0:
        return dict(default)
    return {"x": x, "y": y, "w": w, "h": h}


@dataclass
class TaskSpec:
    task_id: str = "default"
    instruction: str = ""
    camera_roi: dict[str, float] = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0})
    home_roi: dict[str, float] = field(default_factory=lambda: {"x": 0.3, "y": 0.25, "w": 0.4, "h": 0.5})
    safety: dict[str, Any] = field(
        default_factory=lambda: {
            "max_step_ms": 800,
            "max_episode_s": 30.0,
            "stop_every_steps": 1,
            "lost_visible_stop_s": 1.0,
        }
    )
    policy_params: dict[str, float] = field(
        default_factory=lambda: {
            "default_duration_ms": 350.0,
            "default_speed": 0.5,
            "center_margin": 0.12,
            "turn_duration_ms": 220.0,
            "strafe_duration_ms": 220.0,
        }
    )
    # Optional bounds for params (min/max); if missing, generic clamp is applied.
    policy_param_bounds: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "instruction": self.instruction,
            "camera_roi": dict(self.camera_roi),
            "home_roi": dict(self.home_roi),
            "safety": dict(self.safety),
            "policy_params": dict(self.policy_params),
            "policy_param_bounds": dict(self.policy_param_bounds),
        }

    def apply_patch(self, patch: dict[str, Any]) -> list[str]:
        """
        Applies a constrained patch and returns a list of applied keys.

        Allowed:
        - patch.policy_params: numeric values only, clamped to bounds.
        """
        applied: list[str] = []
        if not isinstance(patch, dict):
            return applied

        pp = patch.get("policy_params")
        if isinstance(pp, dict):
            if len(pp) > 32:
                # Hard limit: refuse massive patches.
                return applied
            for k, v in pp.items():
                if not isinstance(k, str) or not k.strip():
                    continue
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    continue
                value = float(v)
                bounds = self.policy_param_bounds.get(k)
                if isinstance(bounds, dict) and isinstance(bounds.get("min"), (int, float)) and isinstance(bounds.get("max"), (int, float)):
                    value = _clamp(value, float(bounds["min"]), float(bounds["max"]))
                else:
                    # Generic clamp to avoid runaway params.
                    value = _clamp(value, -1e6, 1e6)
                self.policy_params[k] = value
                applied.append(f"policy_params.{k}")
        return applied


def load_taskspec(path: str | None, *, instruction_override: str | None = None) -> TaskSpec:
    if not path:
        spec = TaskSpec()
        if instruction_override is not None:
            spec.instruction = instruction_override
        return spec

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise RuntimeError("taskspec must be a JSON object")

    spec = TaskSpec()
    spec.task_id = str(raw.get("task_id") or spec.task_id)
    spec.instruction = str(raw.get("instruction") or "")
    if instruction_override is not None:
        spec.instruction = instruction_override

    spec.camera_roi = _as_norm_rect(raw.get("camera_roi"), spec.camera_roi)
    spec.home_roi = _as_norm_rect(raw.get("home_roi"), spec.home_roi)
    if isinstance(raw.get("safety"), dict):
        spec.safety.update(raw["safety"])
    if isinstance(raw.get("policy_params"), dict):
        for k, v in raw["policy_params"].items():
            if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool):
                spec.policy_params[k] = float(v)
    if isinstance(raw.get("policy_param_bounds"), dict):
        spec.policy_param_bounds = raw["policy_param_bounds"]

    return spec


def save_taskspec(path: str, spec: TaskSpec) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec.to_dict(), f, indent=2, ensure_ascii=True)
    os.replace(tmp, path)

