import { NextResponse } from "next/server";
import { createMecanumPlan } from "@/lib/mecanum_planner";
import type { MecanumPlanRequest } from "@/lib/mecanum_types";
import { ValidationError } from "@/lib/validate";

interface BadRequestResponse {
  error: "BAD_REQUEST" | string;
  message: string;
  details?: unknown;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function badRequest(message: string, details?: unknown): NextResponse<BadRequestResponse> {
  return NextResponse.json(
    {
      error: "BAD_REQUEST",
      message,
      ...(details !== undefined ? { details } : {})
    },
    { status: 400 }
  );
}

function parseBody(body: unknown): MecanumPlanRequest {
  if (!isObject(body)) {
    throw new ValidationError("Request body must be a JSON object.");
  }

  const instruction = body.instruction;
  if (typeof instruction !== "string" || !instruction.trim()) {
    throw new ValidationError("instruction must be a non-empty string.", { instruction });
  }

  const default_duration_ms = body.default_duration_ms;
  const max_steps = body.max_steps;

  return {
    instruction,
    ...(default_duration_ms !== undefined ? { default_duration_ms: default_duration_ms as number } : {}),
    ...(max_steps !== undefined ? { max_steps: max_steps as number } : {})
  };
}

export async function handleMecanumPlanRequest(request: Request): Promise<NextResponse> {
  let body: unknown;
  let correlationId = request.headers.get("x-correlation-id") || `mecanum-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  try {
    body = await request.json();
  } catch (error) {
    return badRequest("Invalid JSON body.", { cause: (error as Error).message });
  }
  if (isObject(body) && typeof body.correlation_id === "string" && body.correlation_id.trim()) {
    correlationId = body.correlation_id.trim();
  }

  try {
    const parsed = parseBody(body);
    const response = await createMecanumPlan(parsed);
    console.log(JSON.stringify({ event: "mecanum.plan.ok", correlation_id: correlationId, instruction: parsed.instruction, plan: response.plan }));
    return NextResponse.json(response, { status: 200 });
  } catch (error) {
    if (error instanceof ValidationError) {
      console.log(JSON.stringify({ event: "mecanum.plan.error", correlation_id: correlationId, message: error.message, details: error.details ?? null }));
      return NextResponse.json(
        {
          error: error.code,
          message: error.message,
          ...(error.details !== undefined ? { details: error.details } : {})
        },
        { status: 400 }
      );
    }

    return NextResponse.json(
      {
        error: "INTERNAL_ERROR",
        message: "Unexpected mecanum planner failure."
      },
      { status: 500 }
    );
  }
}
