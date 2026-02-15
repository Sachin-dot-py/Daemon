from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


@dataclass(frozen=True)
class BBox:
    x: float
    y: float
    w: float
    h: float

    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def area(self) -> float:
        return self.w * self.h


@dataclass(frozen=True)
class TrackerOutput:
    bbox: BBox | None
    visibility_confidence: float
    edge_margin: float
    debug: dict[str, Any]


class MotionTracker:
    def __init__(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV (cv2) is required for tracking")
        self._bg = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=16, detectShadows=False)

    def update(self, frame_bgr: np.ndarray, *, roi: dict[str, float] | None = None) -> TrackerOutput:
        assert cv2 is not None
        h, w = frame_bgr.shape[:2]

        rx, ry, rw, rh = (0.0, 0.0, 1.0, 1.0)
        if isinstance(roi, dict):
            try:
                rx = float(roi.get("x", 0.0))
                ry = float(roi.get("y", 0.0))
                rw = float(roi.get("w", 1.0))
                rh = float(roi.get("h", 1.0))
            except Exception:
                rx, ry, rw, rh = (0.0, 0.0, 1.0, 1.0)
        x0 = int(_clamp(rx, 0.0, 1.0) * w)
        y0 = int(_clamp(ry, 0.0, 1.0) * h)
        x1 = int(_clamp(rx + rw, 0.0, 1.0) * w)
        y1 = int(_clamp(ry + rh, 0.0, 1.0) * h)
        if x1 - x0 < 10 or y1 - y0 < 10:
            x0, y0, x1, y1 = 0, 0, w, h

        cropped = frame_bgr[y0:y1, x0:x1]
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        mask = self._bg.apply(gray)
        mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)[1]
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, np.ones((5, 5), np.uint8))

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        best_area = 0.0
        for c in contours:
            area = float(cv2.contourArea(c))
            if area > best_area:
                best_area = area
                best = c

        if best is None or best_area <= 50.0:
            return TrackerOutput(bbox=None, visibility_confidence=0.0, edge_margin=0.0, debug={"reason": "no_motion_blob"})

        x, y, bw, bh = cv2.boundingRect(best)
        # Convert to full-frame normalized bbox.
        fx = (x0 + x) / w
        fy = (y0 + y) / h
        fw = bw / w
        fh = bh / h
        bbox = BBox(x=_clamp(fx, 0.0, 1.0), y=_clamp(fy, 0.0, 1.0), w=_clamp(fw, 0.0, 1.0 - fx), h=_clamp(fh, 0.0, 1.0 - fy))

        area_norm = bbox.area()
        conf = _clamp(area_norm * 10.0, 0.05, 0.95)

        # Margin to ROI edges (normalized).
        roi_left = rx
        roi_top = ry
        roi_right = rx + rw
        roi_bottom = ry + rh
        margin = min(
            bbox.x - roi_left,
            bbox.y - roi_top,
            roi_right - (bbox.x + bbox.w),
            roi_bottom - (bbox.y + bbox.h),
        )
        margin = _clamp(margin, 0.0, 1.0)

        return TrackerOutput(
            bbox=bbox,
            visibility_confidence=float(conf),
            edge_margin=float(margin),
            debug={"area_norm": area_norm, "mask_contours": len(contours)},
        )

