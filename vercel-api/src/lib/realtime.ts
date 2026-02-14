import { ValidationError } from "@/lib/validate";

export type RealtimeEventType = "start" | "observe" | "stop";
export type EvaluationDecision = "MATCH" | "MISMATCH" | "UNSURE";

export interface RealtimeObservation {
  timestamp_ms: number;
  audio_rms: number;
  video_frame_jpeg_base64?: string;
}

export interface RealtimeEvaluateRequest {
  event: RealtimeEventType;
  session_id?: string;
  expected_outcome: string;
  current_code: string;
  telemetry_tail?: string[];
  observation?: RealtimeObservation;
}

export interface RealtimeEvaluateResponse {
  session_id: string;
  status: "READY" | "MONITORING" | "ENDED";
  decision: EvaluationDecision;
  confidence: number;
  message: string;
  should_update_code: boolean;
  updated_code?: string;
  patch_summary?: string;
}

interface StoredObservation {
  timestampMs: number;
  audioRms: number;
  telemetryTail: string[];
}

interface RealtimeSession {
  id: string;
  expectedOutcome: string;
  currentCode: string;
  startedAtMs: number;
  observations: StoredObservation[];
}

interface CodeUpdateProposal {
  updatedCode: string;
  patchSummary: string;
}

interface ModelEvaluation {
  decision: EvaluationDecision;
  confidence: number;
  message: string;
  shouldUpdateCode: boolean;
  updatedCode?: string;
  patchSummary?: string;
}

const sessions = new Map<string, RealtimeSession>();
const MAX_SESSION_OBSERVATIONS = 180;
const STOPWORDS = new Set([
  "then",
  "with",
  "into",
  "onto",
  "from",
  "that",
  "this",
  "should",
  "would",
  "about",
  "after",
  "before",
  "while",
  "where",
  "make",
  "have",
  "must"
]);
const MOTION_HINTS = /\b(move|moving|turn|rotate|drive|open|close|lift|drop|spin|go|forward|backward|grip)\b/i;
const STILL_HINTS = /\b(stop|still|hold|steady|idle|quiet|rest)\b/i;
const ACTIVE_TELEMETRY_HINTS = /\b(run|fwd|bwd|turn|grip|home|moving|speed|velocity|rpm|motor|active)\b/i;

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function asStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value)) {
    throw new ValidationError(`${field} must be an array of strings.`, { field, value });
  }

  const parsed = value.map((entry, index) => {
    if (typeof entry !== "string") {
      throw new ValidationError(`${field}[${index}] must be a string.`, { field, index, value: entry });
    }
    return entry;
  });

  return parsed;
}

function parseObservation(value: unknown): RealtimeObservation {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ValidationError("observation must be an object when event=observe.");
  }

  const payload = value as Record<string, unknown>;
  if (typeof payload.timestamp_ms !== "number" || !Number.isFinite(payload.timestamp_ms)) {
    throw new ValidationError("observation.timestamp_ms must be a finite number.");
  }

  if (typeof payload.audio_rms !== "number" || !Number.isFinite(payload.audio_rms)) {
    throw new ValidationError("observation.audio_rms must be a finite number.");
  }

  const observation: RealtimeObservation = {
    timestamp_ms: payload.timestamp_ms,
    audio_rms: payload.audio_rms
  };

  if (payload.video_frame_jpeg_base64 !== undefined) {
    if (typeof payload.video_frame_jpeg_base64 !== "string") {
      throw new ValidationError("observation.video_frame_jpeg_base64 must be a string when provided.");
    }

    observation.video_frame_jpeg_base64 = payload.video_frame_jpeg_base64;
  }

  return observation;
}

export function parseRealtimeRequest(body: unknown): RealtimeEvaluateRequest {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new ValidationError("Request body must be a JSON object.");
  }

  const payload = body as Record<string, unknown>;
  const event = payload.event;

  if (event !== "start" && event !== "observe" && event !== "stop") {
    throw new ValidationError("event must be one of: start, observe, stop.");
  }

  if (typeof payload.expected_outcome !== "string" || !payload.expected_outcome.trim()) {
    throw new ValidationError("expected_outcome must be a non-empty string.");
  }

  if (typeof payload.current_code !== "string" || !payload.current_code.trim()) {
    throw new ValidationError("current_code must be a non-empty string.");
  }

  if (payload.session_id !== undefined && typeof payload.session_id !== "string") {
    throw new ValidationError("session_id must be a string when provided.");
  }

  return {
    event,
    session_id: payload.session_id as string | undefined,
    expected_outcome: payload.expected_outcome,
    current_code: payload.current_code,
    telemetry_tail:
      payload.telemetry_tail === undefined ? [] : asStringArray(payload.telemetry_tail, "telemetry_tail"),
    observation: event === "observe" ? parseObservation(payload.observation) : undefined
  };
}

function getOrCreateSession(request: RealtimeEvaluateRequest): RealtimeSession {
  if (request.session_id) {
    const existing = sessions.get(request.session_id);
    if (!existing) {
      throw new ValidationError("Unknown session_id for realtime evaluator.", { session_id: request.session_id });
    }
    existing.expectedOutcome = request.expected_outcome;
    existing.currentCode = request.current_code;
    return existing;
  }

  const id = crypto.randomUUID();
  const session: RealtimeSession = {
    id,
    expectedOutcome: request.expected_outcome,
    currentCode: request.current_code,
    startedAtMs: Date.now(),
    observations: []
  };
  sessions.set(id, session);
  return session;
}

function extractExpectedKeywords(text: string): string[] {
  const tokens = text
    .toLowerCase()
    .match(/[a-z]{4,}/g)
    ?.filter((token) => !STOPWORDS.has(token))
    .slice(0, 10);

  return tokens ?? [];
}

function proposeCodeUpdate(currentCode: string, expectedOutcome: string, reason: string): CodeUpdateProposal {
  const timingMatch = currentCode.match(/\b(\d{2,5})\b/);
  if (timingMatch) {
    const current = Number(timingMatch[1]);
    const direction = STILL_HINTS.test(expectedOutcome) ? 0.85 : 1.15;
    const next = Math.max(1, Math.round(current * direction));
    return {
      updatedCode: currentCode.replace(timingMatch[1], String(next)),
      patchSummary: `Adjusted control value ${current} -> ${next} based on observed behavior (${reason}).`
    };
  }

  const patchNote = [
    "",
    "// DAEMON_AUTO_TUNE",
    `// intent: ${expectedOutcome}`,
    `// reason: ${reason}`,
    "// action: tighten command gating and verify actuator completion before returning success"
  ].join("\n");

  return {
    updatedCode: `${currentCode.trimEnd()}\n${patchNote}\n`,
    patchSummary: "Added auto-tune guidance comment to prompt safer control behavior."
  };
}

function fallbackEvaluation(session: RealtimeSession): ModelEvaluation {
  const latest = session.observations.at(-1);
  if (!latest) {
    return {
      decision: "UNSURE",
      confidence: 0.4,
      message: "Waiting for first observation frame.",
      shouldUpdateCode: false
    };
  }

  const expected = session.expectedOutcome.toLowerCase();
  const telemetryText = latest.telemetryTail.join(" ").toLowerCase();
  const keywords = extractExpectedKeywords(expected);
  const covered = keywords.filter((token) => telemetryText.includes(token)).length;
  const keywordCoverage = keywords.length > 0 ? covered / keywords.length : 0;
  const audioActivity = clamp(latest.audioRms / 0.08, 0, 1);
  const telemetryActivity = ACTIVE_TELEMETRY_HINTS.test(telemetryText) ? 0.35 : 0;
  const activity = clamp(audioActivity + telemetryActivity, 0, 1);
  const motionExpected = MOTION_HINTS.test(expected);
  const stillExpected = STILL_HINTS.test(expected);
  const sampleCount = session.observations.length;

  if (motionExpected && activity >= 0.45) {
    return {
      decision: "MATCH",
      confidence: clamp(0.58 + activity * 0.25 + keywordCoverage * 0.17, 0.55, 0.97),
      message: "Observed active behavior aligned with expected motion-oriented outcome.",
      shouldUpdateCode: false
    };
  }

  if (stillExpected && activity <= 0.25) {
    return {
      decision: "MATCH",
      confidence: clamp(0.56 + (1 - activity) * 0.2 + keywordCoverage * 0.24, 0.55, 0.95),
      message: "Observed stable/quiet behavior aligned with expected hold or stop state.",
      shouldUpdateCode: false
    };
  }

  if (sampleCount >= 2 && motionExpected && activity <= 0.18) {
    const update = proposeCodeUpdate(
      session.currentCode,
      session.expectedOutcome,
      "expected movement was not detected in recent webcam/mic samples"
    );
    return {
      decision: "MISMATCH",
      confidence: 0.72,
      message: "Expected device motion was not visible from recent observations.",
      shouldUpdateCode: true,
      updatedCode: update.updatedCode,
      patchSummary: update.patchSummary
    };
  }

  if (sampleCount >= 2 && stillExpected && activity >= 0.6) {
    const update = proposeCodeUpdate(
      session.currentCode,
      session.expectedOutcome,
      "device remained active while expected behavior was to hold still"
    );
    return {
      decision: "MISMATCH",
      confidence: 0.7,
      message: "Device appears active/noisy when expected outcome required stable behavior.",
      shouldUpdateCode: true,
      updatedCode: update.updatedCode,
      patchSummary: update.patchSummary
    };
  }

  return {
    decision: "UNSURE",
    confidence: clamp(0.45 + sampleCount * 0.03 + keywordCoverage * 0.08, 0.42, 0.68),
    message: "Need more observations to determine if behavior matches expected outcome.",
    shouldUpdateCode: false
  };
}

async function evaluateWithOpenAI(
  session: RealtimeSession,
  request: RealtimeEvaluateRequest
): Promise<ModelEvaluation | null> {
  const apiKey = process.env.OPENAI_API_KEY;
  const observation = request.observation;

  if (!apiKey || !observation?.video_frame_jpeg_base64) {
    return null;
  }

  try {
    const model = process.env.OPENAI_REALTIME_REVIEW_MODEL ?? "gpt-4o-mini";
    const telemetryText = (request.telemetry_tail ?? []).slice(-8).join("\n");
    const content: Array<Record<string, unknown>> = [
      {
        type: "text",
        text: [
          `Expected outcome: ${request.expected_outcome}`,
          `Current code:\n${request.current_code}`,
          `Recent telemetry:\n${telemetryText || "(none)"}`,
          `audio_rms=${observation.audio_rms.toFixed(4)}`,
          "Assess whether behavior matches expected outcome and suggest a code update only if mismatch is clear.",
          "Return JSON: decision(MATCH|MISMATCH|UNSURE), confidence(0..1), message, should_update_code(boolean), updated_code(optional), patch_summary(optional)."
        ].join("\n")
      },
      {
        type: "image_url",
        image_url: {
          url: `data:image/jpeg;base64,${observation.video_frame_jpeg_base64}`
        }
      }
    ];

    const completionResponse = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model,
        temperature: 0.1,
        response_format: { type: "json_object" },
        messages: [
          {
            role: "system",
            content:
              "You evaluate robot/device behavior from observations. Be conservative. Only mark MATCH or MISMATCH when evidence is clear."
          },
          {
            role: "user",
            content
          }
        ]
      })
    });

    if (!completionResponse.ok) {
      return null;
    }

    const payload = (await completionResponse.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };

    const raw = payload.choices?.[0]?.message?.content;
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as {
      decision?: string;
      confidence?: number;
      message?: string;
      should_update_code?: boolean;
      updated_code?: string;
      patch_summary?: string;
    };

    if (parsed.decision !== "MATCH" && parsed.decision !== "MISMATCH" && parsed.decision !== "UNSURE") {
      return null;
    }

    return {
      decision: parsed.decision,
      confidence:
        typeof parsed.confidence === "number" && Number.isFinite(parsed.confidence)
          ? clamp(parsed.confidence, 0, 1)
          : 0.55,
      message: typeof parsed.message === "string" ? parsed.message : "Model evaluation completed.",
      shouldUpdateCode: Boolean(parsed.should_update_code),
      updatedCode: typeof parsed.updated_code === "string" && parsed.updated_code.trim() ? parsed.updated_code : undefined,
      patchSummary:
        typeof parsed.patch_summary === "string" && parsed.patch_summary.trim()
          ? parsed.patch_summary
          : undefined
    };
  } catch {
    return null;
  }
}

export async function evaluateRealtimeRequest(
  request: RealtimeEvaluateRequest
): Promise<RealtimeEvaluateResponse> {
  const session = getOrCreateSession(request);
  session.expectedOutcome = request.expected_outcome;
  session.currentCode = request.current_code;

  if (request.event === "start") {
    return {
      session_id: session.id,
      status: "READY",
      decision: "UNSURE",
      confidence: 0.4,
      message: "Realtime session started. Begin streaming webcam/mic observations.",
      should_update_code: false
    };
  }

  if (request.event === "stop") {
    sessions.delete(session.id);
    return {
      session_id: session.id,
      status: "ENDED",
      decision: "UNSURE",
      confidence: 0.5,
      message: "Realtime session stopped.",
      should_update_code: false
    };
  }

  if (!request.observation) {
    throw new ValidationError("observation is required for event=observe.");
  }

  session.observations.push({
    timestampMs: request.observation.timestamp_ms,
    audioRms: request.observation.audio_rms,
    telemetryTail: (request.telemetry_tail ?? []).slice(-12)
  });

  if (session.observations.length > MAX_SESSION_OBSERVATIONS) {
    session.observations.splice(0, session.observations.length - MAX_SESSION_OBSERVATIONS);
  }

  const modelEvaluation = await evaluateWithOpenAI(session, request);
  const evaluation = modelEvaluation ?? fallbackEvaluation(session);
  let updatedCode = evaluation.updatedCode;
  let patchSummary = evaluation.patchSummary;

  if (evaluation.shouldUpdateCode && !updatedCode) {
    const proposal = proposeCodeUpdate(session.currentCode, session.expectedOutcome, evaluation.message);
    updatedCode = proposal.updatedCode;
    patchSummary = proposal.patchSummary;
  }

  return {
    session_id: session.id,
    status: "MONITORING",
    decision: evaluation.decision,
    confidence: clamp(evaluation.confidence, 0, 1),
    message: evaluation.message,
    should_update_code: evaluation.shouldUpdateCode,
    ...(updatedCode ? { updated_code: updatedCode } : {}),
    ...(patchSummary ? { patch_summary: patchSummary } : {})
  };
}
