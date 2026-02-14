import { NextResponse } from "next/server";
import { evaluateRealtimeRequest, parseRealtimeRequest } from "@/lib/realtime";
import { ValidationError } from "@/lib/validate";

export const runtime = "nodejs";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization"
};

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: corsHeaders
  });
}

export async function POST(request: Request) {
  let body: unknown;

  try {
    body = await request.json();
  } catch (error) {
    return NextResponse.json(
      {
        error: "BAD_REQUEST",
        message: "Invalid JSON body.",
        details: { cause: (error as Error).message }
      },
      { status: 400, headers: corsHeaders }
    );
  }

  try {
    const parsed = parseRealtimeRequest(body);
    const response = await evaluateRealtimeRequest(parsed);
    return NextResponse.json(response, { status: 200, headers: corsHeaders });
  } catch (error) {
    if (error instanceof ValidationError) {
      return NextResponse.json(
        {
          error: error.code,
          message: error.message,
          ...(error.details !== undefined ? { details: error.details } : {})
        },
        { status: 400, headers: corsHeaders }
      );
    }

    return NextResponse.json(
      {
        error: "INTERNAL_ERROR",
        message: "Unexpected realtime evaluator failure."
      },
      { status: 500, headers: corsHeaders }
    );
  }
}
