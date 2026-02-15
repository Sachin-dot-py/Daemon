import { ValidationError } from "@/lib/validate";
import type { MecanumCmd, MecanumPlanRequest, MecanumPlanResponse, MecanumPlanStep } from "@/lib/mecanum_types";

const ALLOWED_CMDS: ReadonlySet<string> = new Set(["F", "B", "L", "R", "Q", "E", "S"]);
type CanonicalMoveDirection = "forward" | "backward" | "left" | "right";
type CanonicalTurnDirection = "left" | "right";
type CanonicalAction =
  | { type: "MOVE"; direction: CanonicalMoveDirection; distance_m?: number; speed?: number }
  | { type: "TURN"; direction: CanonicalTurnDirection; angle_deg?: number; speed?: number }
  | { type: "STOP" };

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function clampInt(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, Math.trunc(value)));
}

function normalizeStep(value: unknown): MecanumPlanStep | null {
  if (!isObject(value)) return null;
  const cmd = typeof value.cmd === "string" ? value.cmd.trim().toUpperCase() : "";
  const duration = typeof value.duration_ms === "number" ? value.duration_ms : Number(value.duration_ms);
  if (!ALLOWED_CMDS.has(cmd)) return null;
  if (!Number.isFinite(duration)) return null;
  return {
    cmd: cmd as MecanumCmd,
    duration_ms: clampInt(duration, 0, 10_000)
  };
}

function ensureStop(plan: MecanumPlanStep[]): MecanumPlanStep[] {
  if (plan.length === 0) return [{ cmd: "S", duration_ms: 0 }];
  const last = plan[plan.length - 1];
  if (last.cmd === "S") return plan;
  return [...plan, { cmd: "S", duration_ms: 0 }];
}

function canonicalToMecanumPlan(actions: CanonicalAction[], defaultDurationMs: number, maxSteps: number): MecanumPlanStep[] {
  const plan: MecanumPlanStep[] = [];
  const push = (cmd: MecanumCmd, durationMs: number) => {
    if (plan.length < maxSteps) {
      plan.push({ cmd, duration_ms: clampInt(durationMs, 0, 10_000) });
    }
  };

  for (const action of actions) {
    if (action.type === "STOP") {
      push("S", 0);
      continue;
    }
    if (action.type === "TURN") {
      const cmd: MecanumCmd = action.direction === "left" ? "Q" : "E";
      const duration = clampInt(Math.max(120, Math.round((Math.abs(action.angle_deg ?? 90) / 90) * defaultDurationMs)), 0, 10_000);
      push(cmd, duration);
      continue;
    }

    const directionMap: Record<CanonicalMoveDirection, MecanumCmd> = {
      forward: "F",
      backward: "B",
      left: "L",
      right: "R"
    };
    const cmd = directionMap[action.direction];
    const duration = clampInt(Math.max(120, Math.round((action.distance_m ?? 1) * defaultDurationMs)), 0, 10_000);
    push(cmd, duration);
  }

  return ensureStop(plan.slice(0, maxSteps));
}

function fallbackHeuristicPlan(instruction: string, defaultDurationMs: number, maxSteps: number): MecanumPlanResponse {
  const text = instruction.toLowerCase();
  const plan: MecanumPlanStep[] = [];

  const push = (cmd: MecanumCmd, duration_ms: number) => {
    if (plan.length >= maxSteps) return;
    plan.push({ cmd, duration_ms: clampInt(duration_ms, 0, 10_000) });
  };

  if (/\bcircle\b/.test(text)) {
    for (let i = 0; i < Math.min(18, maxSteps - 1); i += 1) {
      push("F", Math.max(120, Math.round(defaultDurationMs * 0.35)));
      push("E", 120);
    }
    return { explanation: "Approximate a circle using repeated forward + rotate-right segments, then stop.", plan: ensureStop(plan) };
  }

  if (/\bsquare\b/.test(text)) {
    for (let i = 0; i < 4; i += 1) {
      push("F", Math.max(200, defaultDurationMs));
      push("E", 420);
    }
    return { explanation: "Drive a rough square (forward, rotate right 90), then stop.", plan: ensureStop(plan) };
  }

  if (/\bstop\b/.test(text)) {
    return { explanation: "Stop.", plan: [{ cmd: "S", duration_ms: 0 }] };
  }
  if (/\b(turn|rotate)\s+left\b|\bcounterclockwise\b/.test(text)) {
    return { explanation: "Turn left, then stop.", plan: ensureStop([{ cmd: "Q", duration_ms: defaultDurationMs }]) };
  }
  if (/\b(turn|rotate)\s+right\b|\bclockwise\b/.test(text)) {
    return { explanation: "Turn right, then stop.", plan: ensureStop([{ cmd: "E", duration_ms: defaultDurationMs }]) };
  }
  if (/\b(backward|back up|reverse|go back|move back)\b/.test(text)) {
    return { explanation: "Move backward, then stop.", plan: ensureStop([{ cmd: "B", duration_ms: defaultDurationMs }]) };
  }
  if (/\b(left|strafe left|slide left)\b/.test(text)) {
    return { explanation: "Move left, then stop.", plan: ensureStop([{ cmd: "L", duration_ms: defaultDurationMs }]) };
  }
  if (/\b(right|strafe right|slide right)\b/.test(text)) {
    return { explanation: "Move right, then stop.", plan: ensureStop([{ cmd: "R", duration_ms: defaultDurationMs }]) };
  }
  if (/\b(forward|go forward|move forward)\b/.test(text)) {
    return { explanation: "Move forward, then stop.", plan: ensureStop([{ cmd: "F", duration_ms: defaultDurationMs }]) };
  }

  throw new ValidationError("No supported mecanum action found in instruction.");
}

export async function createMecanumPlan(request: MecanumPlanRequest): Promise<MecanumPlanResponse> {
  const instruction = request.instruction?.trim();
  if (!instruction) {
    throw new ValidationError("instruction must be a non-empty string.");
  }

  const defaultDurationMs = clampInt(typeof request.default_duration_ms === "number" ? request.default_duration_ms : 500, 50, 5000);
  const maxSteps = clampInt(typeof request.max_steps === "number" ? request.max_steps : 28, 1, 80);

  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) {
    return fallbackHeuristicPlan(instruction, defaultDurationMs, maxSteps);
  }

  const model = process.env.OPENAI_MECANUM_PLANNER_MODEL ?? "gpt-4o-mini";

  const completionResponse = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model,
      temperature: 0.2,
      response_format: { type: "json_object" },
      messages: [
        {
          role: "system",
          content: [
            "You are a motion planner for a mecanum robot controlled by primitive commands.",
            "You must output ONLY valid JSON.",
            "Output format: {\"explanation\": string, \"canonical_actions\": [{\"type\":\"MOVE|TURN|STOP\", ...}], \"max_steps\": number}",
            "Canonical actions schema:",
            "MOVE(direction: forward|backward|left|right, distance_m?: number, speed?: number)",
            "TURN(direction: left|right, angle_deg?: number, speed?: number)",
            "STOP()",
            `Constraints: keep canonical_actions length <= ${maxSteps}.`,
            "Map semantic variants to canonical directions (e.g., strafe left/go to your left => MOVE left; reverse/back up => MOVE backward).",
            "For shapes like a circle: approximate using small repeated segments (e.g. forward+rotate) rather than one long move."
          ].join("\n")
        },
        {
          role: "user",
          content: [
            `Instruction: ${instruction}`,
            `Default duration hint (ms): ${defaultDurationMs}`,
            "Return JSON only."
          ].join("\n")
        }
      ]
    })
  });

  if (!completionResponse.ok) {
    return fallbackHeuristicPlan(instruction, defaultDurationMs, maxSteps);
  }

  const payload = (await completionResponse.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };

  const raw = payload.choices?.[0]?.message?.content;
  if (!raw) {
    return fallbackHeuristicPlan(instruction, defaultDurationMs, maxSteps);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return fallbackHeuristicPlan(instruction, defaultDurationMs, maxSteps);
  }

  if (!isObject(parsed) || !Array.isArray(parsed.canonical_actions)) {
    return fallbackHeuristicPlan(instruction, defaultDurationMs, maxSteps);
  }

  const explanation = typeof parsed.explanation === "string" && parsed.explanation.trim() ? parsed.explanation.trim() : "Planned motion.";
  const canonicalActions = parsed.canonical_actions
    .map((action): CanonicalAction | null => {
      if (!isObject(action) || typeof action.type !== "string") return null;
      if (action.type === "STOP") return { type: "STOP" };
      if (action.type === "MOVE") {
        const direction = typeof action.direction === "string" ? action.direction : "";
        if (!["forward", "backward", "left", "right"].includes(direction)) return null;
        return {
          type: "MOVE",
          direction: direction as CanonicalMoveDirection,
          ...(typeof action.distance_m === "number" ? { distance_m: action.distance_m } : {}),
          ...(typeof action.speed === "number" ? { speed: action.speed } : {})
        };
      }
      if (action.type === "TURN") {
        const direction = typeof action.direction === "string" ? action.direction : "";
        if (!["left", "right"].includes(direction)) return null;
        return {
          type: "TURN",
          direction: direction as CanonicalTurnDirection,
          ...(typeof action.angle_deg === "number" ? { angle_deg: action.angle_deg } : {}),
          ...(typeof action.speed === "number" ? { speed: action.speed } : {})
        };
      }
      return null;
    })
    .filter(Boolean) as CanonicalAction[];

  const plan = canonicalToMecanumPlan(canonicalActions.slice(0, maxSteps), defaultDurationMs, maxSteps);

  if (plan.length === 0) {
    return fallbackHeuristicPlan(instruction, defaultDurationMs, maxSteps);
  }

  return { explanation, plan };
}
