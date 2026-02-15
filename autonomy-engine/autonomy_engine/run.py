from __future__ import annotations

import argparse
import base64
import json
import os
import random
import time
import uuid
from typing import Any

from .camera import OpenCVCamera, jpeg_base64
from .judge import judge_episode
from .logging import JsonlLogger
from .orchestrator_client import OrchestratorClient
from .perception import CachedPerception, maybe_openai_perception
from .policy import plan_next_step_fallback, plan_next_step_openai
from .semantics import infer_capabilities, infer_semantics
from .shield import home_ok, maybe_override
from .taskspec import load_taskspec, save_taskspec
from .tracker import MotionTracker


def _now_ms() -> int:
    return int(time.time() * 1000)


def _tracker_dict(tracker_out) -> dict[str, Any]:
    bbox = tracker_out.bbox
    return {
        "visible_conf": tracker_out.visibility_confidence,
        "edge_margin": tracker_out.edge_margin,
        "bbox": bbox.__dict__ if bbox else None,
        "debug": tracker_out.debug,
    }


def _write_attempt_artifacts(out_dir: str, attempt_id: str, frames_b64: list[str], steps: list[dict[str, Any]], spec_dict: dict[str, Any]) -> str:
    base = os.path.join(out_dir, attempt_id)
    os.makedirs(os.path.join(base, "frames"), exist_ok=True)

    for idx, b64 in enumerate(frames_b64[:8]):
        try:
            raw = base64.b64decode(b64.encode("ascii"))
        except Exception:
            continue
        with open(os.path.join(base, "frames", f"frame_{idx}.jpg"), "wb") as f:
            f.write(raw)

    with open(os.path.join(base, "steps.json"), "w", encoding="utf-8") as f:
        json.dump({"steps": steps}, f, indent=2, ensure_ascii=True)
    with open(os.path.join(base, "taskspec.json"), "w", encoding="utf-8") as f:
        json.dump(spec_dict, f, indent=2, ensure_ascii=True)
    return base


def _auto_explore(spec) -> list[str]:
    """
    Best-effort parameter exploration when judge provides no patch.
    Returns list of changed keys.
    """
    sigma = float(spec.policy_params.get("explore_sigma", 0.12))
    if sigma <= 0:
        return []

    max_step_ms = float(spec.safety.get("max_step_ms", 800))
    changed: list[str] = []

    def perturb(key: str, lo: float, hi: float) -> None:
        if key not in spec.policy_params:
            return
        v = float(spec.policy_params[key])
        factor = 1.0 + random.gauss(0.0, sigma)
        nv = max(lo, min(hi, v * factor))
        if abs(nv - v) > 1e-9:
            spec.policy_params[key] = nv
            changed.append(key)

    perturb("default_speed", 0.05, 1.0)
    perturb("default_duration_ms", 80.0, max_step_ms)
    perturb("turn_duration_ms", 80.0, max_step_ms)
    perturb("strafe_duration_ms", 80.0, max_step_ms)
    perturb("center_margin", 0.05, 0.25)
    return changed


def run(args: argparse.Namespace) -> int:
    logger = JsonlLogger(path=args.log_path)
    client = OrchestratorClient(base_url=args.orchestrator)

    status = client.status()
    system_manifest = status.get("system_manifest") if isinstance(status.get("system_manifest"), dict) else {}

    semantics = infer_semantics(
        system_manifest,
        use_openai=bool(args.openai_semantics),
        openai_model=args.openai_model,
    )
    caps = infer_capabilities(system_manifest, semantics)

    spec = load_taskspec(args.taskspec, instruction_override=args.instruction)
    if not spec.instruction.strip():
        raise RuntimeError("--instruction is required (or set instruction in taskspec)")

    cam = OpenCVCamera(index=args.camera, width=args.width, height=args.height)
    tracker = MotionTracker()
    openai_cache: CachedPerception | None = None

    logger.log(
        "autonomy.start",
        correlation_id=args.run_id,
        orchestrator=args.orchestrator,
        instruction=spec.instruction,
        caps=caps.__dict__,
        openai_semantics=bool(args.openai_semantics),
    )

    try:
        for attempt in range(int(args.attempts)):
            attempt_id = f"{args.run_id}-a{attempt}"
            start_ms = _now_ms()
            logger.log("autonomy.attempt.start", correlation_id=attempt_id, attempt=attempt)

            # Reset to home (best-effort).
            home_deadline = start_ms + int(float(args.reset_timeout_s) * 1000)
            while _now_ms() < home_deadline:
                frame = cam.read()
                t_out = tracker.update(frame, roi=spec.camera_roi)
                if t_out.bbox is None:
                    # For reset, allow OpenAI bbox fallback (low frequency via cache).
                    b64 = jpeg_base64(frame, quality=args.jpeg_quality)
                    t_out, openai_cache = maybe_openai_perception(
                        cached=openai_cache,
                        frame_jpeg_b64=b64,
                        roi=spec.camera_roi,
                        hint="robot device (the one being controlled)",
                        model=args.openai_model,
                    )
                if home_ok(t_out.bbox, spec):
                    break
                decision = maybe_override(tracker=t_out, spec=spec, caps=caps, system_manifest=system_manifest)
                if decision is None:
                    # Not at edge, but not home; do nothing for now.
                    break
                logger.log(
                    "autonomy.reset.step",
                    correlation_id=attempt_id,
                    tracker=_tracker_dict(t_out),
                    decision={"reason": decision.reason, "plan": decision.plan},
                )
                client.execute_plan(decision.plan, correlation_id=attempt_id)
                time.sleep(0.05)

            # Episode rollout.
            frames_b64: list[str] = []
            executed_steps: list[dict[str, Any]] = []
            max_steps = int(args.max_steps)
            episode_deadline = start_ms + int(float(spec.safety.get("max_episode_s", args.max_episode_s)) * 1000)

            for step_idx in range(max_steps):
                if _now_ms() > episode_deadline:
                    logger.log("autonomy.episode.timeout", correlation_id=attempt_id, step=step_idx)
                    break

                frame_before = cam.read()
                before_b64 = jpeg_base64(frame_before, quality=args.jpeg_quality)
                if step_idx in {0, max_steps // 2}:
                    frames_b64.append(before_b64)

                t_out = tracker.update(frame_before, roi=spec.camera_roi)
                if t_out.bbox is None:
                    # Best-effort OpenAI bbox fallback so non-motion situations still work.
                    t_out, openai_cache = maybe_openai_perception(
                        cached=openai_cache,
                        frame_jpeg_b64=before_b64,
                        roi=spec.camera_roi,
                        hint="robot device (the one being controlled)",
                        model=args.openai_model,
                    )

                shield = maybe_override(tracker=t_out, spec=spec, caps=caps, system_manifest=system_manifest)
                if shield is not None:
                    plan = shield.plan
                    reason = f"shield:{shield.reason}"
                    overridden = True
                else:
                    plan, reason = plan_next_step_openai(
                        instruction=spec.instruction,
                        system_manifest=system_manifest,
                        semantics=semantics,
                        caps=caps,
                        tracker=t_out,
                        spec=spec,
                        model=args.openai_model,
                    )
                    if plan and plan[0].get("type") == "STOP":
                        plan2, r2 = plan_next_step_fallback(instruction=spec.instruction)
                        if r2 != "fallback_noop":
                            plan, reason = plan2, r2
                    overridden = False

                step_record = {
                    "step": step_idx,
                    "tracker": _tracker_dict(t_out),
                    "plan": plan,
                    "reason": reason,
                    "overridden": overridden,
                }
                logger.log("autonomy.step", correlation_id=attempt_id, **step_record)

                executed_steps.append(step_record)
                client.execute_plan(plan, correlation_id=attempt_id)

                frame_after = cam.read()
                after_b64 = jpeg_base64(frame_after, quality=args.jpeg_quality)
                if step_idx == max_steps - 1:
                    frames_b64.append(after_b64)

                if plan and plan[0].get("type") == "STOP":
                    break

            # Ensure we have start/end frames for judging.
            if frames_b64:
                if len(frames_b64) == 1:
                    frames_b64.append(frames_b64[0])
            else:
                frames_b64.append(jpeg_base64(cam.read(), quality=args.jpeg_quality))
                frames_b64.append(frames_b64[0])

            attempt_dir = _write_attempt_artifacts(args.out_dir, attempt_id, frames_b64, executed_steps, spec.to_dict())
            logger.log("autonomy.attempt.saved", correlation_id=attempt_id, out_dir=attempt_dir)

            judge = judge_episode(
                instruction=spec.instruction,
                frames_jpeg_b64=frames_b64,
                executed_summary={"steps": executed_steps[-6:], "caps": caps.__dict__},
                policy_params=spec.policy_params,
                model=args.openai_model,
            )
            logger.log(
                "autonomy.judge",
                correlation_id=attempt_id,
                verdict=judge.verdict,
                score=judge.score,
                confidence=judge.confidence,
                failure_modes=judge.failure_modes,
                what_went_wrong=judge.what_went_wrong,
                fix_proposal=judge.fix_proposal,
            )

            if judge.verdict == "success":
                logger.log("autonomy.success", correlation_id=attempt_id, attempt=attempt)
                return 0

            applied = []
            if isinstance(judge.fix_proposal, dict):
                applied = spec.apply_patch(judge.fix_proposal)
            if applied:
                logger.log("autonomy.patch.applied", correlation_id=attempt_id, applied=applied, policy_params=spec.policy_params)
                if args.taskspec:
                    save_taskspec(args.taskspec, spec)
            else:
                if args.auto_explore:
                    changed = _auto_explore(spec)
                    logger.log("autonomy.explore", correlation_id=attempt_id, changed=changed, policy_params=spec.policy_params)
                    if changed and args.taskspec:
                        save_taskspec(args.taskspec, spec)
                else:
                    logger.log("autonomy.patch.none", correlation_id=attempt_id)

        return 2
    finally:
        try:
            client.stop(correlation_id=args.run_id)
        except Exception:
            pass
        cam.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="DAEMON Autonomy Engine")
    ap.add_argument("--orchestrator", default="http://127.0.0.1:5055", help="Orchestrator HTTP base URL")
    ap.add_argument("--instruction", default=None, help="Task instruction text (overrides taskspec)")
    ap.add_argument("--taskspec", default=None, help="Path to taskspec JSON (will be updated if patches apply)")
    ap.add_argument("--camera", type=int, default=0, help="OpenCV camera index (default: 0)")
    ap.add_argument("--width", type=int, default=320, help="Capture width")
    ap.add_argument("--height", type=int, default=240, help="Capture height")
    ap.add_argument("--jpeg-quality", type=int, default=70, help="JPEG quality (0-100)")
    ap.add_argument("--attempts", type=int, default=8, help="Max attempts (execute→judge→patch cycles)")
    ap.add_argument("--max-steps", type=int, default=8, help="Max steps per attempt")
    ap.add_argument("--max-episode-s", type=float, default=30.0, help="Default max seconds per attempt (if taskspec missing)")
    ap.add_argument("--reset-timeout-s", type=float, default=6.0, help="Best-effort reset-to-home timeout")
    ap.add_argument("--openai-model", default="gpt-4.1-mini", help="OpenAI model for planner/judge")
    ap.add_argument("--openai-semantics", action="store_true", help="Use OpenAI to refine manifest semantics (cached)")
    ap.add_argument(
        "--auto-explore",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If judge provides no patch, perturb numeric policy_params and retry (default: enabled)",
    )
    ap.add_argument("--log-path", default="logs/autonomy_trace.jsonl", help="JSONL trace path")
    ap.add_argument("--out-dir", default=".daemon/episodes", help="Directory for episode artifacts (frames/steps)")
    ap.add_argument("--run-id", default=None, help="Correlation ID (default: random)")
    args = ap.parse_args()

    if args.run_id is None:
        args.run_id = f"auto-{uuid.uuid4().hex[:10]}"
    if args.instruction is None and args.taskspec is None:
        raise SystemExit("--instruction or --taskspec is required")

    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
