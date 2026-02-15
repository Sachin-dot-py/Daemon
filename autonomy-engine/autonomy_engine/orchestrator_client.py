from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


def normalize_base_url(url: str) -> str:
    base = (url or "").strip()
    if not base:
        raise ValueError("orchestrator base URL is required")
    return base.rstrip("/")


@dataclass(frozen=True)
class OrchestratorClient:
    base_url: str
    timeout_s: float = 5.0

    def _request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        base = normalize_base_url(self.base_url)
        url = f"{base}{path}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                **(headers or {}),
            },
            method=method.upper(),
        )
        timeout = self.timeout_s if timeout_s is None else float(timeout_s)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            raise RuntimeError(f"orchestrator {method} {path} failed: HTTP {exc.code}: {raw or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"orchestrator {method} {path} failed: {exc.reason}") from exc

        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        if not isinstance(parsed, dict):
            raise RuntimeError(f"orchestrator {method} {path} returned non-object JSON")
        return parsed

    def status(self) -> dict[str, Any]:
        data = self._request_json("GET", "/status", body=None, headers=None)
        if not data.get("ok"):
            raise RuntimeError(f"orchestrator /status not ok: {data}")
        return data

    def telemetry(self) -> dict[str, Any]:
        # Best-effort; older orchestrators may not expose /telemetry.
        try:
            data = self._request_json("GET", "/telemetry", body=None, headers=None, timeout_s=2.0)
        except Exception:
            return {}
        if not data.get("ok"):
            return {}
        snapshot = data.get("telemetry_snapshot")
        return snapshot if isinstance(snapshot, dict) else {}

    def execute_plan(self, plan: list[dict[str, Any]], correlation_id: str | None = None) -> dict[str, Any]:
        headers = {"X-Correlation-Id": correlation_id} if correlation_id else None
        data = self._request_json("POST", "/execute_plan", body={"plan": plan, "correlation_id": correlation_id}, headers=headers)
        if not data.get("ok"):
            raise RuntimeError(f"orchestrator /execute_plan not ok: {data}")
        return data

    def stop(self, correlation_id: str | None = None) -> dict[str, Any]:
        headers = {"X-Correlation-Id": correlation_id} if correlation_id else None
        data = self._request_json("POST", "/stop", body={}, headers=headers)
        if not data.get("ok"):
            raise RuntimeError(f"orchestrator /stop not ok: {data}")
        return data

