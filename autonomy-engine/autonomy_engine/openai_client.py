from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


_FILE_ENV_CACHE: dict[str, str] | None = None


def _parse_dotenv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        out[key] = value
    return out


def _load_file_env() -> dict[str, str]:
    global _FILE_ENV_CACHE  # noqa: PLW0603
    if _FILE_ENV_CACHE is not None:
        return _FILE_ENV_CACHE

    merged: dict[str, str] = {}
    cwd = os.getcwd()
    candidates = [
        os.path.join(cwd, ".env.local"),
        os.path.join(cwd, ".env"),
    ]
    for path in candidates:
        try:
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                merged.update(_parse_dotenv(f.read()))
        except Exception:
            continue

    _FILE_ENV_CACHE = merged
    return merged


def _env_value(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    file_env = _load_file_env()
    for key in keys:
        value = file_env.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def openai_api_key() -> str | None:
    return _env_value("OPENAI_API_KEY", "OPEN_AI_API_KEY")


def extract_responses_text(payload: Any) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"]

    if isinstance(payload, dict) and isinstance(payload.get("output"), list):
        for item in payload["output"]:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"].strip():
                    return part["text"]

    return ""


def call_responses_api(payload: dict[str, Any], timeout_s: float = 15.0) -> dict[str, Any]:
    api_key = openai_api_key()
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY (or OPEN_AI_API_KEY)")

    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        raise RuntimeError(f"OpenAI responses HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI responses request failed: {exc.reason}") from exc

    parsed = json.loads(raw) if raw else {}
    if not isinstance(parsed, dict):
        raise RuntimeError("OpenAI responses returned non-object JSON")
    return parsed


def responses_json_schema(
    *,
    model: str,
    schema_name: str,
    schema: dict[str, Any],
    system_text: str,
    user_content: list[dict[str, Any]],
    temperature: float = 0.0,
    timeout_s: float = 15.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload: dict[str, Any] = {
        "model": model,
        "temperature": float(temperature),
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_text}],
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    }

    raw = call_responses_api(payload, timeout_s=timeout_s)
    text = extract_responses_text(raw)
    try:
        obj = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI returned non-JSON text: {text[:200]}") from exc
    if not isinstance(obj, dict):
        raise RuntimeError("OpenAI returned non-object JSON")
    return obj, raw
