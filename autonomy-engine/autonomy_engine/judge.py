from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

from .logging import now_iso
from .openai_client import openai_api_key, responses_json_schema


def _default_cache_path() -> str:
    return os.path.join(os.getcwd(), ".daemon", "judge_cache.json")


def _hash_key(instruction: str, frame_b64_list: list[str]) -> str:
    h = hashlib.sha256()
    h.update(instruction.strip().encode("utf-8"))
    for b64 in frame_b64_list:
        h.update(b64[:2048].encode("ascii", errors="ignore"))
        h.update(str(len(b64)).encode("ascii"))
    return h.hexdigest()[:20]


def _load_cache(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            parsed = json.load(f)
    except FileNotFoundError:
        return {"version": 1, "entries": {}}
    except Exception:
        return {"version": 1, "entries": {}}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("entries"), dict):
        return {"version": 1, "entries": {}}
    return parsed


def _save_cache(path: str, cache: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=True)
    os.replace(tmp, path)


@dataclass(frozen=True)
class JudgeResult:
    verdict: str
    score: float
    confidence: float
    failure_modes: list[str]
    what_went_wrong: str
    fix_proposal: dict[str, Any]
    raw: dict[str, Any] | None = None


def judge_episode(
    *,
    instruction: str,
    frames_jpeg_b64: list[str],
    executed_summary: dict[str, Any],
    policy_params: dict[str, float],
    model: str = "gpt-4.1-mini",
    cache_path: str | None = None,
) -> JudgeResult:
    if not openai_api_key():
        return JudgeResult(
            verdict="uncertain",
            score=0.0,
            confidence=0.0,
            failure_modes=["missing_api_key"],
            what_went_wrong="OPENAI_API_KEY missing; judge disabled.",
            fix_proposal={},
            raw=None,
        )

    frames = [b64 for b64 in frames_jpeg_b64 if isinstance(b64, str) and b64.strip()][:8]
    cache_file = cache_path or _default_cache_path()
    cache = _load_cache(cache_file)
    key = _hash_key(instruction, frames)
    cached = cache.get("entries", {}).get(key)
    if isinstance(cached, dict) and isinstance(cached.get("verdict"), str):
        return JudgeResult(
            verdict=str(cached.get("verdict")),
            score=float(cached.get("score", 0.0)),
            confidence=float(cached.get("confidence", 0.0)),
            failure_modes=[str(x) for x in (cached.get("failure_modes") or []) if isinstance(x, str)],
            what_went_wrong=str(cached.get("what_went_wrong") or ""),
            fix_proposal=cached.get("fix_proposal") if isinstance(cached.get("fix_proposal"), dict) else {},
            raw=cached.get("raw") if isinstance(cached.get("raw"), dict) else None,
        )

    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "verdict": {"type": "string", "enum": ["success", "failure", "uncertain"]},
            "score": {"type": "number", "minimum": 0, "maximum": 1},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "failure_modes": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "what_went_wrong": {"type": "string"},
            "fix_proposal": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "policy_params": {"type": "object", "additionalProperties": {"type": "number"}},
                },
            },
        },
        "required": ["verdict", "score", "confidence", "failure_modes", "what_went_wrong", "fix_proposal"],
    }

    system_text = (
        "You are a strict robot judge.\n"
        "You are given an instruction, a summary of what actions were executed, and keyframes.\n"
        "Decide if the robot is doing the intended action correctly.\n"
        "If failure, explain what went wrong and propose minimal numeric parameter tweaks under fix_proposal.policy_params.\n"
        "If you are not confident from the evidence, output verdict=uncertain.\n"
        "Return strict JSON only."
    )

    user_parts: list[dict[str, Any]] = []
    user_parts.append({"type": "input_text", "text": f"Instruction: {instruction}"})
    user_parts.append({"type": "input_text", "text": f"Executed summary JSON: {json.dumps(executed_summary, separators=(',', ':'))}"})
    user_parts.append({"type": "input_text", "text": f"Current policy_params JSON: {json.dumps(policy_params, separators=(',', ':'))}"})
    for idx, b64 in enumerate(frames):
        user_parts.append({"type": "input_text", "text": f"Frame {idx}:"})
        user_parts.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"})

    out, raw = responses_json_schema(
        model=model,
        schema_name="daemon_episode_judge",
        schema=schema,
        system_text=system_text,
        user_content=user_parts,
        temperature=0.0,
        timeout_s=20.0,
    )

    verdict = str(out.get("verdict") or "uncertain")
    score = float(out.get("score") or 0.0)
    confidence = float(out.get("confidence") or 0.0)
    failure_modes = out.get("failure_modes") if isinstance(out.get("failure_modes"), list) else []
    what = str(out.get("what_went_wrong") or "")
    fix = out.get("fix_proposal") if isinstance(out.get("fix_proposal"), dict) else {}

    result = JudgeResult(
        verdict=verdict,
        score=max(0.0, min(1.0, score)),
        confidence=max(0.0, min(1.0, confidence)),
        failure_modes=[str(x) for x in failure_modes if isinstance(x, str)],
        what_went_wrong=what,
        fix_proposal=fix if isinstance(fix, dict) else {},
        raw=raw,
    )

    cache.setdefault("entries", {})[key] = {
        "ts": now_iso(),
        "verdict": result.verdict,
        "score": result.score,
        "confidence": result.confidence,
        "failure_modes": result.failure_modes,
        "what_went_wrong": result.what_went_wrong,
        "fix_proposal": result.fix_proposal,
        "raw": raw,
    }
    _save_cache(cache_file, cache)
    return result
