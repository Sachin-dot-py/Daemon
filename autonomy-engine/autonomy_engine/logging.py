from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time() % 1) * 1000):03d}Z"


@dataclass
class JsonlLogger:
    path: str
    _lock: threading.Lock = threading.Lock()

    def log(self, event: str, correlation_id: str | None = None, **fields: Any) -> None:
        payload: dict[str, Any] = {"ts": now_iso(), "event": event}
        if correlation_id:
            payload["correlation_id"] = correlation_id
        payload.update(fields)

        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        line = json.dumps(payload, ensure_ascii=True)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

