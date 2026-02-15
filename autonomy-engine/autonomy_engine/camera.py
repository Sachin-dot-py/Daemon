from __future__ import annotations

import base64
from dataclasses import dataclass


try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


@dataclass
class OpenCVCamera:
    index: int = 0
    width: int = 320
    height: int = 240

    def __post_init__(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV (cv2) is required. Install autonomy-engine requirements.txt.")
        self._cap = cv2.VideoCapture(int(self.index))
        if not self._cap.isOpened():
            raise RuntimeError(f"Failed to open camera index {self.index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))

    def read(self):
        assert cv2 is not None
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise RuntimeError("Failed to read camera frame")
        return frame

    def close(self) -> None:
        try:
            self._cap.release()
        except Exception:
            pass


def jpeg_base64(frame, *, quality: int = 70) -> str:
    if cv2 is None:
        raise RuntimeError("OpenCV (cv2) is required")
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("Failed to encode JPEG")
    return base64.b64encode(buf.tobytes()).decode("ascii")

