from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable

from .logging import now_iso
from .manifest import CommandRef, iter_commands, manifest_hash
from .openai_client import responses_json_schema


SEMANTICS_CACHE_VERSION = 1


KNOWN_TAGS: list[str] = [
    # Mobility
    "locomotion.forward",
    "locomotion.backward",
    "locomotion.turn",
    "locomotion.strafe",
    # Manipulation
    "end_effector.grip",
    # Perception / IO
    "camera.snapshot",
    "light.set",
    "sound.play",
    "pose.set",
    "dance.step",
    # Safety
    "safety.estop",
    # Fallback
    "generic.action",
]


def _blob(command_spec: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("token", "description"):
        v = command_spec.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    nlp = command_spec.get("nlp")
    if isinstance(nlp, dict):
        for k in ("synonyms", "examples"):
            v = nlp.get(k)
            if isinstance(v, list):
                parts.extend(str(item) for item in v if isinstance(item, str))
    args = command_spec.get("args")
    if isinstance(args, list):
        for arg in args:
            if not isinstance(arg, dict):
                continue
            name = arg.get("name")
            if isinstance(name, str):
                parts.append(name)
            enum = arg.get("enum")
            if isinstance(enum, list):
                parts.extend(str(item) for item in enum)
    return " ".join(parts).lower()


def infer_tags_heuristic(command_spec: dict[str, Any]) -> tuple[list[str], float]:
    token = str(command_spec.get("token") or "").strip().upper()
    text = _blob(command_spec)
    tags: set[str] = set()
    confidence = 0.45

    def hit(*needles: str) -> bool:
        return any(n in text for n in needles)

    # Safety
    if token in {"ESTOP", "E_STOP", "EMERGENCY_STOP"} or hit("estop", "e-stop", "emergency stop"):
        tags.add("safety.estop")
        confidence = max(confidence, 0.9)

    # Mobility
    if token in {"FWD", "FORWARD"} or hit("forward", "move forward", "go forward", "drive forward"):
        tags.add("locomotion.forward")
        confidence = max(confidence, 0.85 if token in {"FWD", "FORWARD"} else 0.65)

    if token in {"BWD", "BACKWARD", "REV"} or hit("backward", "reverse", "move back", "go back"):
        tags.add("locomotion.backward")
        confidence = max(confidence, 0.85 if token in {"BWD", "BACKWARD", "REV"} else 0.65)

    if token in {"TURN", "ROTATE", "SPIN"} or hit("turn", "rotate", "spin"):
        tags.add("locomotion.turn")
        confidence = max(confidence, 0.85 if token in {"TURN", "ROTATE", "SPIN"} else 0.65)

    if token in {"STRAFE", "SLIDE"} or hit("strafe", "slide", "lateral"):
        tags.add("locomotion.strafe")
        confidence = max(confidence, 0.8 if token in {"STRAFE", "SLIDE"} else 0.6)

    # Manipulation
    if token in {"GRIP", "GRAB", "CLAW"} or hit("grip", "gripper", "claw", "grab"):
        tags.add("end_effector.grip")
        confidence = max(confidence, 0.9 if token in {"GRIP", "GRAB", "CLAW"} else 0.7)

    # Camera
    if token in {"SNAP", "SNAPSHOT", "CAMERA", "CAM"} or hit("camera", "snapshot", "take picture", "capture frame"):
        tags.add("camera.snapshot")
        confidence = max(confidence, 0.85 if token in {"SNAP", "SNAPSHOT", "CAMERA", "CAM"} else 0.6)

    # Other IO
    if token in {"LED", "LIGHT"} or hit("led", "light"):
        tags.add("light.set")
        confidence = max(confidence, 0.7)

    if token in {"BEEP", "SOUND"} or hit("beep", "sound", "tone"):
        tags.add("sound.play")
        confidence = max(confidence, 0.65)

    if token in {"POSE", "SERVO", "ANGLE"} or hit("pose", "servo", "joint", "angle", "position"):
        tags.add("pose.set")
        confidence = max(confidence, 0.55)

    if token in {"DANCE"} or hit("dance"):
        tags.add("dance.step")
        confidence = max(confidence, 0.55)

    if not tags:
        tags.add("generic.action")
        confidence = 0.4

    return sorted(tags), float(confidence)


def _default_cache_path() -> str:
    return os.path.join(os.getcwd(), ".daemon", "semantics_cache.json")


def load_cache(path: str | None = None) -> dict[str, Any]:
    cache_path = path or _default_cache_path()
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            parsed = json.load(f)
    except FileNotFoundError:
        return {"version": SEMANTICS_CACHE_VERSION, "by_manifest": {}}
    except Exception:
        return {"version": SEMANTICS_CACHE_VERSION, "by_manifest": {}}
    if not isinstance(parsed, dict):
        return {"version": SEMANTICS_CACHE_VERSION, "by_manifest": {}}
    if parsed.get("version") != SEMANTICS_CACHE_VERSION:
        return {"version": SEMANTICS_CACHE_VERSION, "by_manifest": {}}
    if not isinstance(parsed.get("by_manifest"), dict):
        parsed["by_manifest"] = {}
    return parsed


def save_cache(cache: dict[str, Any], path: str | None = None) -> None:
    cache_path = path or _default_cache_path()
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=True)
    os.replace(tmp, cache_path)


def _openai_classify_tags(
    commands: list[CommandRef],
    model: str,
    timeout_s: float,
) -> dict[str, dict[str, Any]]:
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "commands": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "key": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string", "enum": KNOWN_TAGS}},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["key", "tags", "confidence"],
                },
            }
        },
        "required": ["commands"],
    }

    compact = []
    for ref in commands:
        spec = ref.spec
        compact.append(
            {
                "key": ref.key,
                "token": ref.token,
                "description": spec.get("description"),
                "args": spec.get("args"),
                "nlp": spec.get("nlp"),
            }
        )

    system_text = (
        "You classify DAEMON robot command tokens into semantic tags.\n"
        "Return only the tags that are clearly supported by the command.\n"
        "If unsure, return ['generic.action'].\n"
        "Tags must be chosen from the allowed enum list.\n"
        "Confidence is 0..1."
    )
    user_content = [
        {"type": "input_text", "text": f"Commands JSON:\n{json.dumps(compact, separators=(',',':'))}"},
    ]

    out, _raw = responses_json_schema(
        model=model,
        schema_name="daemon_command_semantics",
        schema=schema,
        system_text=system_text,
        user_content=user_content,
        temperature=0.0,
        timeout_s=timeout_s,
    )

    items = out.get("commands")
    if not isinstance(items, list):
        return {}
    by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        tags = item.get("tags")
        conf = item.get("confidence")
        if not isinstance(key, str) or not isinstance(tags, list) or not isinstance(conf, (int, float)):
            continue
        filtered = [t for t in tags if isinstance(t, str) and t in KNOWN_TAGS]
        by_key[key] = {"tags": filtered or ["generic.action"], "confidence": float(conf)}
    return by_key


def infer_semantics(
    system_manifest: dict[str, Any],
    *,
    cache_path: str | None = None,
    use_openai: bool = False,
    openai_model: str = "gpt-4.1-mini",
    openai_timeout_s: float = 20.0,
) -> dict[str, dict[str, Any]]:
    """
    Returns mapping: command_key -> {tags: [...], confidence: float, source: str}.
    """
    m_hash = manifest_hash(system_manifest)
    cache = load_cache(cache_path)
    by_manifest = cache.setdefault("by_manifest", {})
    entry = by_manifest.setdefault(m_hash, {"commands": {}, "updated_at": now_iso()})
    cmds_cache = entry.setdefault("commands", {})
    if not isinstance(cmds_cache, dict):
        cmds_cache = {}
        entry["commands"] = cmds_cache

    commands = list(iter_commands(system_manifest))

    # Fill from cache when present.
    out: dict[str, dict[str, Any]] = {}
    missing: list[CommandRef] = []
    for ref in commands:
        cached = cmds_cache.get(ref.key)
        if isinstance(cached, dict) and isinstance(cached.get("tags"), list):
            out[ref.key] = {
                "tags": [t for t in cached.get("tags", []) if isinstance(t, str)],
                "confidence": float(cached.get("confidence", 0.5)),
                "source": str(cached.get("source", "cache")),
            }
            continue
        missing.append(ref)

    # Heuristic pass for anything missing.
    for ref in missing:
        tags, conf = infer_tags_heuristic(ref.spec)
        record = {"tags": tags, "confidence": conf, "source": "heuristic"}
        out[ref.key] = record
        cmds_cache[ref.key] = {**record, "updated_at": now_iso()}

    # Optional OpenAI refinement (only for low-confidence or generic).
    if use_openai:
        to_refine: list[CommandRef] = []
        for ref in commands:
            rec = out.get(ref.key) or {}
            tags = rec.get("tags") if isinstance(rec.get("tags"), list) else []
            conf = float(rec.get("confidence", 0.0))
            if "generic.action" in tags or conf < 0.55:
                to_refine.append(ref)

        # Keep the request bounded.
        to_refine = to_refine[:60]
        if to_refine:
            try:
                refined = _openai_classify_tags(to_refine, model=openai_model, timeout_s=openai_timeout_s)
            except Exception:
                refined = {}
            for key, rec in refined.items():
                record = {
                    "tags": rec.get("tags", ["generic.action"]),
                    "confidence": float(rec.get("confidence", 0.5)),
                    "source": "openai",
                }
                out[key] = record
                cmds_cache[key] = {**record, "updated_at": now_iso()}

    entry["updated_at"] = now_iso()
    cache["version"] = SEMANTICS_CACHE_VERSION
    save_cache(cache, cache_path)
    return out


@dataclass(frozen=True)
class CapabilityMapping:
    mobility_target: str | None
    fwd_token: str | None
    bwd_token: str | None
    turn_token: str | None
    strafe_token: str | None
    grip_target: str | None
    grip_token: str | None
    estop_target: str | None
    estop_token: str | None


def infer_capabilities(system_manifest: dict[str, Any], semantics: dict[str, dict[str, Any]]) -> CapabilityMapping:
    # Score nodes by how many locomotion tags they expose.
    node_scores: dict[str, int] = {}
    cmd_by_node: dict[str, list[CommandRef]] = {}
    for ref in iter_commands(system_manifest):
        cmd_by_node.setdefault(ref.node_id, []).append(ref)
        tags = semantics.get(ref.key, {}).get("tags", [])
        if isinstance(tags, list) and any(isinstance(t, str) and t.startswith("locomotion.") for t in tags):
            node_scores[ref.node_id] = node_scores.get(ref.node_id, 0) + 1

    mobility_target = None
    if node_scores:
        mobility_target = sorted(node_scores.items(), key=lambda kv: kv[1], reverse=True)[0][0]

    def pick(node_id: str | None, want_tag: str) -> str | None:
        if not node_id:
            return None
        best: tuple[float, str] | None = None
        for ref in cmd_by_node.get(node_id, []):
            rec = semantics.get(ref.key) or {}
            tags = rec.get("tags") if isinstance(rec.get("tags"), list) else []
            if want_tag not in tags:
                continue
            conf = float(rec.get("confidence", 0.0))
            if best is None or conf > best[0]:
                best = (conf, ref.token.upper())
        return best[1] if best else None

    fwd = pick(mobility_target, "locomotion.forward")
    bwd = pick(mobility_target, "locomotion.backward")
    turn = pick(mobility_target, "locomotion.turn")
    strafe = pick(mobility_target, "locomotion.strafe")

    # Grip can be on a different node.
    grip_target = None
    grip_token = None
    best_grip: tuple[float, str, str] | None = None
    for ref in iter_commands(system_manifest):
        rec = semantics.get(ref.key) or {}
        tags = rec.get("tags") if isinstance(rec.get("tags"), list) else []
        if "end_effector.grip" not in tags:
            continue
        conf = float(rec.get("confidence", 0.0))
        if best_grip is None or conf > best_grip[0]:
            best_grip = (conf, ref.node_id, ref.token.upper())
    if best_grip:
        grip_target = best_grip[1]
        grip_token = best_grip[2]

    # E-stop token (optional).
    estop_target = None
    estop_token = None
    best_estop: tuple[float, str, str] | None = None
    for ref in iter_commands(system_manifest):
        rec = semantics.get(ref.key) or {}
        tags = rec.get("tags") if isinstance(rec.get("tags"), list) else []
        if "safety.estop" not in tags:
            continue
        conf = float(rec.get("confidence", 0.0))
        if best_estop is None or conf > best_estop[0]:
            best_estop = (conf, ref.node_id, ref.token.upper())
    if best_estop:
        estop_target = best_estop[1]
        estop_token = best_estop[2]

    return CapabilityMapping(
        mobility_target=mobility_target,
        fwd_token=fwd,
        bwd_token=bwd,
        turn_token=turn,
        strafe_token=strafe,
        grip_target=grip_target,
        grip_token=grip_token,
        estop_target=estop_target,
        estop_token=estop_token,
    )
