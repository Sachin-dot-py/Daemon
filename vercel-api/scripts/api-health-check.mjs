#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";

function parseDotEnv(text) {
  const result = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    result[key] = value;
  }
  return result;
}

function loadEnvFiles() {
  const cwd = process.cwd();
  const candidates = [
    path.join(cwd, ".env.local"),
    path.join(cwd, ".env"),
    path.join(cwd, "..", ".env.local"),
    path.join(cwd, "..", ".env")
  ];

  const merged = {};
  const loaded = [];

  for (const file of candidates) {
    try {
      if (!fs.existsSync(file)) continue;
      const parsed = parseDotEnv(fs.readFileSync(file, "utf8"));
      Object.assign(merged, parsed);
      loaded.push(file);
    } catch {
      // ignore unreadable files
    }
  }

  return { merged, loaded };
}

function envValue(env, ...keys) {
  for (const key of keys) {
    const value = env[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return undefined;
}

function masked(value) {
  if (!value) return "(missing)";
  if (value.length <= 10) return `${value.slice(0, 2)}***`;
  return `${value.slice(0, 4)}***${value.slice(-4)}`;
}

async function checkOpenAI(apiKey, model) {
  if (!apiKey) {
    return {
      ok: false,
      code: "missing_key",
      detail: "OPENAI_API_KEY/OPEN_AI_API_KEY not configured"
    };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 6000);
  try {
    const resp = await fetch("https://api.openai.com/v1/models", {
      method: "GET",
      headers: {
        Authorization: `Bearer ${apiKey}`
      },
      signal: controller.signal
    });

    if (!resp.ok) {
      const body = await resp.text();
      return {
        ok: false,
        code: `http_${resp.status}`,
        detail: body.slice(0, 180)
      };
    }

    const payload = await resp.json().catch(() => ({}));
    const count = Array.isArray(payload?.data) ? payload.data.length : 0;
    return {
      ok: true,
      code: "ok",
      detail: `Authenticated. models_visible=${count}. configured_model=${model || "gpt-4.1-mini"}`
    };
  } catch (error) {
    return {
      ok: false,
      code: "request_failed",
      detail: error instanceof Error ? error.message : "unknown_error"
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function main() {
  const fileEnv = loadEnvFiles();
  const combined = {
    ...fileEnv.merged,
    ...process.env
  };

  const openaiKey = envValue(combined, "OPENAI_API_KEY", "OPEN_AI_API_KEY");
  const openaiModel = envValue(combined, "OPENAI_VISION_MODEL") || "gpt-4.1-mini";
  const blobToken = envValue(combined, "BLOB_READ_WRITE_TOKEN");
  const publishKey = envValue(combined, "DAEMON_PUBLISH_API_KEY");

  const openai = await checkOpenAI(openaiKey, openaiModel);

  const report = {
    now: new Date().toISOString(),
    cwd: process.cwd(),
    dotenv_files_loaded: fileEnv.loaded,
    keys: {
      OPENAI_API_KEY: {
        present: Boolean(openaiKey),
        masked: masked(openaiKey)
      },
      OPENAI_VISION_MODEL: {
        present: true,
        value: openaiModel
      },
      BLOB_READ_WRITE_TOKEN: {
        present: Boolean(blobToken),
        masked: masked(blobToken)
      },
      DAEMON_PUBLISH_API_KEY: {
        present: Boolean(publishKey),
        masked: masked(publishKey)
      }
    },
    checks: {
      openai_api: openai
    }
  };

  console.log(JSON.stringify(report, null, 2));

  if (!openai.ok) {
    process.exitCode = 1;
  }
}

main();
