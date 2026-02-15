from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from .openai_client import openai_api_key, responses_json_schema
from .tracker import BBox, TrackerOutput


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


@dataclass
class CachedPerception:
    ts_ms: int
    out: TrackerOutput


def detect_robot_bbox_openai(
    *,
    frame_jpeg_b64: str,
    roi: dict[str, float],
    hint: str,
    model: str = "gpt-4.1-mini",
) -> TrackerOutput:
    """
    Best-effort: ask OpenAI to return a bbox for the robot/device being controlled.
    Returns a TrackerOutput with bbox=None on failure.
    """
    if not openai_api_key():
        return TrackerOutput(bbox=None, visibility_confidence=0.0, edge_margin=0.0, debug={"reason": "missing_api_key"})

    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "found": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "bbox": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "x": {"type": "number", "minimum": 0, "maximum": 1},
                            "y": {"type": "number", "minimum": 0, "maximum": 1},
                            "w": {"type": "number", "minimum": 0, "maximum": 1},
                            "h": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": ["x", "y", "w", "h"],
                    },
                ]
            },
        },
        "required": ["found", "confidence", "bbox"],
    }

    system_text = (
        "You locate the robot/device being controlled in the camera frame.\n"
        "Return a single bounding box normalized [0..1].\n"
        "If you cannot confidently identify the robot, return found=false and bbox=null.\n"
        "Return strict JSON only."
    )

    user_content = [
        {"type": "input_text", "text": f"Hint about robot appearance/type: {hint}"},
        {"type": "input_text", "text": f"Camera ROI (normalized) the robot should be within: {json.dumps(roi, separators=(',', ':'))}"},
        {"type": "input_image", "image_url": f"data:image/jpeg;base64,{frame_jpeg_b64}"},
    ]

    out, _raw = responses_json_schema(
        model=model,
        schema_name="daemon_robot_bbox",
        schema=schema,
        system_text=system_text,
        user_content=user_content,
        temperature=0.0,
        timeout_s=12.0,
    )

    found = bool(out.get("found"))
    conf = float(out.get("confidence") or 0.0)
    bbox_raw = out.get("bbox")
    if (not found) or not isinstance(bbox_raw, dict):
        return TrackerOutput(bbox=None, visibility_confidence=0.0, edge_margin=0.0, debug={"reason": "openai_not_found"})

    try:
        bbox = BBox(
            x=_clamp(float(bbox_raw.get("x", 0.0)), 0.0, 1.0),
            y=_clamp(float(bbox_raw.get("y", 0.0)), 0.0, 1.0),
            w=_clamp(float(bbox_raw.get("w", 0.0)), 0.0, 1.0),
            h=_clamp(float(bbox_raw.get("h", 0.0)), 0.0, 1.0),
        )
        if bbox.w <= 0.0 or bbox.h <= 0.0:
            raise ValueError("invalid bbox")
    except Exception:
        return TrackerOutput(bbox=None, visibility_confidence=0.0, edge_margin=0.0, debug={"reason": "openai_bad_bbox"})

    roi_left = float(roi.get("x", 0.0))
    roi_top = float(roi.get("y", 0.0))
    roi_right = roi_left + float(roi.get("w", 1.0))
    roi_bottom = roi_top + float(roi.get("h", 1.0))
    margin = min(
        bbox.x - roi_left,
        bbox.y - roi_top,
        roi_right - (bbox.x + bbox.w),
        roi_bottom - (bbox.y + bbox.h),
    )
    margin = _clamp(margin, 0.0, 1.0)

    return TrackerOutput(
        bbox=bbox,
        visibility_confidence=_clamp(conf, 0.0, 1.0),
        edge_margin=margin,
        debug={"reason": "openai_bbox"},
    )


def maybe_openai_perception(
    *,
    cached: CachedPerception | None,
    frame_jpeg_b64: str,
    roi: dict[str, float],
    hint: str,
    model: str,
    max_age_ms: int = 900,
) -> tuple[TrackerOutput, CachedPerception]:
    now_ms = int(time.time() * 1000)
    if cached and (now_ms - cached.ts_ms) <= max_age_ms and cached.out.bbox is not None:
        return cached.out, cached
    out = detect_robot_bbox_openai(frame_jpeg_b64=frame_jpeg_b64, roi=roi, hint=hint, model=model)
    return out, CachedPerception(ts_ms=now_ms, out=out)

