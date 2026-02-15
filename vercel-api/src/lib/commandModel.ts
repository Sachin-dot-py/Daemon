type TaskType = "stop" | "move-pattern" | "move-if-clear" | "pick-object" | "follow" | "search" | "avoid+approach" | "unknown";
type MotionPattern = "circle" | "square" | "triangle";
type CanonicalMoveDirection = "forward" | "backward" | "left" | "right";
type CanonicalTurnDirection = "left" | "right";
type CanonicalAction =
  | { type: "MOVE"; direction: CanonicalMoveDirection; distance_m?: number; speed?: number }
  | { type: "TURN"; direction: CanonicalTurnDirection; angle_deg?: number; speed?: number }
  | { type: "STOP" };

export interface CommandModelPrediction {
  task_type: TaskType;
  stop_kind?: "normal" | "emergency";
  pattern?: MotionPattern;
  canonical_actions?: CanonicalAction[];
  count?: number;
  distance_m?: number;
}

export interface CommandModelConfig {
  enabled: boolean;
  shadow: boolean;
  url: string | null;
  timeout_ms: number;
  min_confidence: number;
  api_key: string | null;
}

export interface CommandModelInference {
  ok: boolean;
  prediction?: CommandModelPrediction;
  confidence?: number;
  model_version?: string;
  reason?: string;
  latency_ms: number;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseBoolean(value: string | undefined): boolean {
  if (!value) return false;
  const normalized = value.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function parseNumber(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

const TASK_TYPES = new Set<TaskType>(["stop", "move-pattern", "move-if-clear", "pick-object", "follow", "search", "avoid+approach", "unknown"]);
const PATTERNS = new Set<MotionPattern>(["circle", "square", "triangle"]);
const MOVE_DIRECTIONS = new Set<CanonicalMoveDirection>(["forward", "backward", "left", "right"]);
const TURN_DIRECTIONS = new Set<CanonicalTurnDirection>(["left", "right"]);

function parseCanonicalActions(value: unknown): CanonicalAction[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const parsed: CanonicalAction[] = [];
  for (const item of value) {
    if (!isObject(item) || typeof item.type !== "string") {
      return undefined;
    }
    if (item.type === "STOP") {
      parsed.push({ type: "STOP" });
      continue;
    }
    if (item.type === "MOVE") {
      if (typeof item.direction !== "string" || !MOVE_DIRECTIONS.has(item.direction as CanonicalMoveDirection)) {
        return undefined;
      }
      const moveAction: CanonicalAction = { type: "MOVE", direction: item.direction as CanonicalMoveDirection };
      if (typeof item.distance_m === "number" && Number.isFinite(item.distance_m)) {
        moveAction.distance_m = item.distance_m;
      }
      if (typeof item.speed === "number" && Number.isFinite(item.speed)) {
        moveAction.speed = item.speed;
      }
      parsed.push(moveAction);
      continue;
    }
    if (item.type === "TURN") {
      if (typeof item.direction !== "string" || !TURN_DIRECTIONS.has(item.direction as CanonicalTurnDirection)) {
        return undefined;
      }
      const turnAction: CanonicalAction = { type: "TURN", direction: item.direction as CanonicalTurnDirection };
      if (typeof item.angle_deg === "number" && Number.isFinite(item.angle_deg)) {
        turnAction.angle_deg = item.angle_deg;
      }
      if (typeof item.speed === "number" && Number.isFinite(item.speed)) {
        turnAction.speed = item.speed;
      }
      parsed.push(turnAction);
      continue;
    }
    return undefined;
  }
  return parsed;
}

function parsePrediction(value: unknown): CommandModelPrediction | undefined {
  if (!isObject(value)) return undefined;
  if (typeof value.task_type !== "string" || !TASK_TYPES.has(value.task_type as TaskType)) {
    return undefined;
  }

  const parsed: CommandModelPrediction = { task_type: value.task_type as TaskType };

  if (typeof value.stop_kind === "string" && (value.stop_kind === "normal" || value.stop_kind === "emergency")) {
    parsed.stop_kind = value.stop_kind;
  }
  if (typeof value.pattern === "string" && PATTERNS.has(value.pattern as MotionPattern)) {
    parsed.pattern = value.pattern as MotionPattern;
  }

  const canonicalActions = parseCanonicalActions(value.canonical_actions);
  if (canonicalActions) {
    parsed.canonical_actions = canonicalActions;
  }

  if (typeof value.count === "number" && Number.isFinite(value.count)) {
    parsed.count = value.count;
  }
  if (typeof value.distance_m === "number" && Number.isFinite(value.distance_m)) {
    parsed.distance_m = value.distance_m;
  }

  return parsed;
}

export function readCommandModelConfig(): CommandModelConfig {
  const enabled = parseBoolean(process.env.DAEMON_COMMAND_MODEL_ENABLED);
  const shadow = parseBoolean(process.env.DAEMON_COMMAND_MODEL_SHADOW);
  const rawUrl = process.env.DAEMON_COMMAND_MODEL_URL;
  const url = rawUrl && rawUrl.trim() ? rawUrl.trim() : null;
  const timeout_ms = Math.round(clamp(parseNumber(process.env.DAEMON_COMMAND_MODEL_TIMEOUT_MS, 300), 50, 3000));
  const min_confidence = clamp(parseNumber(process.env.DAEMON_COMMAND_MODEL_MIN_CONFIDENCE, 0.7), 0, 1);
  const api_key = process.env.DAEMON_COMMAND_MODEL_API_KEY?.trim() || null;

  return { enabled, shadow, url, timeout_ms, min_confidence, api_key };
}

export async function requestCommandModelPrediction(
  config: CommandModelConfig,
  instruction: string
): Promise<CommandModelInference> {
  const start = Date.now();
  if (!config.url) {
    return { ok: false, reason: "missing_url", latency_ms: 0 };
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeout_ms);

  try {
    const headers: HeadersInit = { "Content-Type": "application/json" };
    if (config.api_key) {
      headers.Authorization = `Bearer ${config.api_key}`;
    }

    const response = await fetch(config.url, {
      method: "POST",
      headers,
      body: JSON.stringify({ instruction }),
      signal: controller.signal
    });

    if (!response.ok) {
      return {
        ok: false,
        reason: `http_${response.status}`,
        latency_ms: Date.now() - start
      };
    }

    const payload: unknown = await response.json();
    if (!isObject(payload)) {
      return { ok: false, reason: "bad_json_shape", latency_ms: Date.now() - start };
    }

    const rootPrediction = parsePrediction(payload.prediction);
    const fallbackPrediction = rootPrediction ? undefined : parsePrediction(payload);
    const prediction = rootPrediction || fallbackPrediction;
    if (!prediction) {
      return { ok: false, reason: "missing_prediction", latency_ms: Date.now() - start };
    }

    const rawConfidence = typeof payload.confidence === "number" ? payload.confidence : 0;
    const confidence = clamp(Number.isFinite(rawConfidence) ? rawConfidence : 0, 0, 1);
    const model_version = typeof payload.model_version === "string" ? payload.model_version : undefined;

    return {
      ok: true,
      prediction,
      confidence,
      model_version,
      latency_ms: Date.now() - start
    };
  } catch (error) {
    const reason = error instanceof Error ? error.name.toLowerCase() : "request_error";
    return { ok: false, reason, latency_ms: Date.now() - start };
  } finally {
    clearTimeout(timer);
  }
}
