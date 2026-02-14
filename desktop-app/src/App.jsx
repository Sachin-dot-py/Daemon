import { useEffect, useMemo, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import "./App.css";

const DEFAULT_VERCEL_BASE_URL = "https://daemon-ten-chi.vercel.app";
const DEFAULT_ORCH_BASE_URL = "http://127.0.0.1:5055";
const FRAME_WIDTH = 320;
const FRAME_HEIGHT = 240;
const CAPTURE_INTERVAL_MS = 300;
const STATUS_POLL_MS = 2000;
const INSTRUCTION = "pick the blue cube";

const VERCEL_BASE_URL = import.meta.env.VITE_VERCEL_BASE_URL || DEFAULT_VERCEL_BASE_URL;
const ORCH_BASE_URL = import.meta.env.VITE_ORCHESTRATOR_BASE_URL || DEFAULT_ORCH_BASE_URL;
const RUNTIME_IS_TAURI = isTauri();

const INITIAL_STATE = {
  stage: "SEARCH",
  scan_dir: 1,
  scan_ticks: 0,
  capabilities: {
    base_target: "base",
    arm_target: "arm",
    base_turn_token: "TURN",
    base_fwd_token: "FWD",
    arm_grip_token: "GRIP"
  }
};

function nowStamp() {
  return new Date().toLocaleTimeString();
}

async function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const full = String(reader.result || "");
      const base64 = full.includes(",") ? full.split(",")[1] : full;
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

async function captureFrameBase64(video, canvas) {
  if (!video || !canvas || video.readyState < 2) {
    return null;
  }

  canvas.width = FRAME_WIDTH;
  canvas.height = FRAME_HEIGHT;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) {
    return null;
  }

  ctx.drawImage(video, 0, 0, FRAME_WIDTH, FRAME_HEIGHT);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.6));
  if (!blob) {
    return null;
  }
  return blobToBase64(blob);
}

async function postVisionJson(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data?.error || data?.message || `HTTP ${resp.status}`);
  }
  return data;
}

function drawOverlay(canvas, perception) {
  if (!canvas) {
    return;
  }

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return;
  }

  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  if (!perception?.found || !perception?.bbox) {
    return;
  }

  const sx = w / FRAME_WIDTH;
  const sy = h / FRAME_HEIGHT;
  const { x, y, w: bw, h: bh } = perception.bbox;

  ctx.strokeStyle = "#1f7cff";
  ctx.lineWidth = 3;
  ctx.strokeRect(x * sx, y * sy, bw * sx, bh * sy);

  const label = `blue ${Number(perception.confidence || 0).toFixed(2)}`;
  ctx.font = "14px ui-monospace, SFMono-Regular, Menlo, monospace";
  const tw = ctx.measureText(label).width;
  ctx.fillStyle = "rgba(0, 0, 0, 0.65)";
  ctx.fillRect(x * sx, Math.max(0, y * sy - 22), tw + 14, 20);
  ctx.fillStyle = "#ffffff";
  ctx.fillText(label, x * sx + 7, Math.max(14, y * sy - 8));
}

async function orchestratorStatus(orchestratorBaseUrl) {
  if (RUNTIME_IS_TAURI) {
    try {
      return await invoke("orchestrator_status", { orchestratorBaseUrl });
    } catch (error) {
      throw new Error(
        `Tauri proxy GET ${orchestratorBaseUrl}/status failed: ${String(error)}. ` +
        "If you are viewing localhost:1420 in a browser tab, use the Tauri app window instead."
      );
    }
  }
  const resp = await fetch(`${orchestratorBaseUrl}/status`);
  if (!resp.ok) {
    throw new Error(`GET ${orchestratorBaseUrl}/status failed: HTTP ${resp.status}`);
  }
  return resp.json();
}

async function orchestratorExecutePlan(orchestratorBaseUrl, plan) {
  if (RUNTIME_IS_TAURI) {
    try {
      return await invoke("orchestrator_execute_plan", { orchestratorBaseUrl, plan });
    } catch (error) {
      throw new Error(
        `Tauri proxy POST ${orchestratorBaseUrl}/execute_plan failed: ${String(error)}. ` +
        "If you are viewing localhost:1420 in a browser tab, use the Tauri app window instead."
      );
    }
  }
  const resp = await fetch(`${orchestratorBaseUrl}/execute_plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan })
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data?.error || `POST ${orchestratorBaseUrl}/execute_plan failed: HTTP ${resp.status}`);
  }
  return data;
}

async function orchestratorStop(orchestratorBaseUrl) {
  if (RUNTIME_IS_TAURI) {
    try {
      return await invoke("orchestrator_stop", { orchestratorBaseUrl });
    } catch (error) {
      throw new Error(
        `Tauri proxy POST ${orchestratorBaseUrl}/stop failed: ${String(error)}. ` +
        "If you are viewing localhost:1420 in a browser tab, use the Tauri app window instead."
      );
    }
  }
  const resp = await fetch(`${orchestratorBaseUrl}/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({})
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data?.error || `POST ${orchestratorBaseUrl}/stop failed: HTTP ${resp.status}`);
  }
  return data;
}

function App() {
  const videoRef = useRef(null);
  const captureCanvasRef = useRef(null);
  const overlayCanvasRef = useRef(null);
  const streamRef = useRef(null);
  const liveTimerRef = useRef(null);
  const inFlightRef = useRef(false);
  const stateRef = useRef(INITIAL_STATE);

  const [liveEnabled, setLiveEnabled] = useState(false);
  const [sendingFrames, setSendingFrames] = useState(false);
  const [fsmState, setFsmState] = useState(INITIAL_STATE);
  const [perception, setPerception] = useState(null);
  const [lastPlan, setLastPlan] = useState([]);
  const [lastDebug, setLastDebug] = useState(null);

  const [dryRun, setDryRun] = useState(false);
  const [orchestratorReachable, setOrchestratorReachable] = useState(false);
  const [lastOrchestratorError, setLastOrchestratorError] = useState("");
  const [lastActionText, setLastActionText] = useState("");
  const [lastActionTimestamp, setLastActionTimestamp] = useState("");
  const [errorText, setErrorText] = useState("");

  const statusText = useMemo(() => {
    if (!liveEnabled) {
      return sendingFrames ? "single-step in progress" : "idle";
    }
    return sendingFrames ? "live / sending frames" : "live / waiting";
  }, [liveEnabled, sendingFrames]);

  useEffect(() => {
    drawOverlay(overlayCanvasRef.current, perception);
  }, [perception]);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        await orchestratorStatus(ORCH_BASE_URL);
        if (cancelled) {
          return;
        }
        setOrchestratorReachable(true);
        setLastOrchestratorError("");
      } catch (error) {
        if (cancelled) {
          return;
        }
        setOrchestratorReachable(false);
        setLastOrchestratorError(String(error));
      }
    };

    poll();
    const interval = setInterval(poll, STATUS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const clearLiveTimer = () => {
    if (liveTimerRef.current) {
      clearInterval(liveTimerRef.current);
      liveTimerRef.current = null;
    }
  };

  const releaseCamera = () => {
    if (streamRef.current) {
      for (const track of streamRef.current.getTracks()) {
        track.stop();
      }
      streamRef.current = null;
    }
  };

  const ensureCamera = async () => {
    if (streamRef.current && videoRef.current?.srcObject) {
      return;
    }

    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480 },
      audio: false
    });

    streamRef.current = stream;
    const video = videoRef.current;
    if (!video) {
      throw new Error("video element unavailable");
    }

    video.srcObject = stream;
    await video.play();

    if (overlayCanvasRef.current) {
      overlayCanvasRef.current.width = 640;
      overlayCanvasRef.current.height = 480;
    }
  };

  const stopLoop = async ({ sendStop }) => {
    clearLiveTimer();
    inFlightRef.current = false;
    setSendingFrames(false);
    setLiveEnabled(false);
    releaseCamera();

    if (sendStop) {
      try {
        await orchestratorStop(ORCH_BASE_URL);
        setOrchestratorReachable(true);
        setLastOrchestratorError("");
        setLastActionText("STOP OK");
        setLastActionTimestamp(nowStamp());
      } catch (error) {
        const msg = String(error);
        setOrchestratorReachable(false);
        setLastOrchestratorError(msg);
        setLastActionText("STOP FAILED");
        setLastActionTimestamp(nowStamp());
        setErrorText(`STOP failed: ${msg}`);
      }
    }
  };

  useEffect(() => {
    return () => {
      stopLoop({ sendStop: false });
    };
  }, []);

  const executeSingleVisionStep = async ({ executePlan }) => {
    if (inFlightRef.current) {
      return;
    }

    inFlightRef.current = true;
    setSendingFrames(true);

    try {
      await ensureCamera();
      const frame_jpeg_base64 = await captureFrameBase64(videoRef.current, captureCanvasRef.current);
      if (!frame_jpeg_base64) {
        throw new Error("camera frame unavailable");
      }

      const visionPayload = {
        frame_jpeg_base64,
        instruction: INSTRUCTION,
        state: stateRef.current,
        system_manifest: null,
        telemetry_snapshot: null
      };

      const visionResponse = await postVisionJson(`${VERCEL_BASE_URL}/api/vision_step`, visionPayload);
      const nextState = visionResponse?.state || stateRef.current;
      const nextPlan = Array.isArray(visionResponse?.plan) ? visionResponse.plan : [];

      stateRef.current = nextState;
      setFsmState(nextState);
      setPerception(visionResponse?.perception || null);
      setLastPlan(nextPlan);
      setLastDebug(visionResponse?.debug || null);
      setErrorText("");

      if (executePlan) {
        const response = await orchestratorExecutePlan(ORCH_BASE_URL, nextPlan);
        const ok = Boolean(response?.ok);
        if (!ok) {
          throw new Error(response?.error || "execute_plan returned non-ok response");
        }
        setOrchestratorReachable(true);
        setLastOrchestratorError("");
        setLastActionText("EXECUTE_PLAN OK");
      } else {
        setLastActionText("DRY RUN: plan not executed");
      }
      setLastActionTimestamp(nowStamp());

      if (String(nextState?.stage || "").toUpperCase() === "DONE" && liveEnabled) {
        await stopLoop({ sendStop: false });
      }
    } catch (error) {
      const msg = String(error);
      setErrorText(msg);
      setOrchestratorReachable(false);
      setLastOrchestratorError(msg);
      setLastActionText("STEP FAILED");
      setLastActionTimestamp(nowStamp());
      if (liveEnabled) {
        await stopLoop({ sendStop: true });
      }
    } finally {
      inFlightRef.current = false;
      setSendingFrames(false);
    }
  };

  const startLiveCamera = async () => {
    try {
      await ensureCamera();
      setFsmState(INITIAL_STATE);
      stateRef.current = INITIAL_STATE;
      setPerception(null);
      setLastPlan([]);
      setLastDebug(null);
      setErrorText("");
      setLiveEnabled(true);

      liveTimerRef.current = setInterval(() => {
        executeSingleVisionStep({ executePlan: !dryRun });
      }, CAPTURE_INTERVAL_MS);
    } catch (error) {
      setErrorText(`Camera start failed: ${String(error)}`);
      await stopLoop({ sendStop: false });
    }
  };

  const handleLiveToggle = async () => {
    if (liveEnabled) {
      await stopLoop({ sendStop: false });
      return;
    }
    await startLiveCamera();
  };

  const handleStop = async () => {
    await stopLoop({ sendStop: true });
  };

  const handleSingleStep = async () => {
    await executeSingleVisionStep({ executePlan: !dryRun });
  };

  return (
    <div className="live-app">
      <header className="header">
        <h1>DAEMON Live Camera</h1>
        <div className="button-row">
          <button onClick={handleLiveToggle} className={liveEnabled ? "btn-live active" : "btn-live"}>
            {liveEnabled ? "Disable Live Camera" : "Enable Live Camera"}
          </button>
          <button onClick={handleSingleStep} className="btn-step">SINGLE STEP</button>
          <button onClick={handleStop} className="btn-stop">STOP</button>
        </div>
      </header>

      <section className="status-bar">
        <span><strong>Status:</strong> {statusText}</span>
        <span><strong>Runtime:</strong> {RUNTIME_IS_TAURI ? "Tauri" : "Browser (fallback mode)"}</span>
        <span><strong>FSM:</strong> {String(fsmState?.stage || "SEARCH")}</span>
        <span><strong>Vision API:</strong> {VERCEL_BASE_URL}</span>
        <span><strong>Orchestrator:</strong> {ORCH_BASE_URL}</span>
        <span><strong>Orchestrator reachable:</strong> {String(orchestratorReachable)}</span>
        <span><strong>Last action:</strong> {lastActionText || "-"}</span>
        <span><strong>Last action at:</strong> {lastActionTimestamp || "-"}</span>
        <span><strong>DRY RUN:</strong> {String(dryRun)}</span>
      </section>

      <section className="toggle-row">
        <label>
          <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
          DRY RUN (do not call execute_plan)
        </label>
      </section>

      {lastOrchestratorError ? (
        <section className="error-box">
          <strong>Last orchestrator error:</strong> {lastOrchestratorError}
        </section>
      ) : null}

      {errorText ? <section className="error-box">{errorText}</section> : null}

      <main className="layout">
        <section className="panel video-panel">
          <h2>Live Preview</h2>
          <div className="video-shell">
            <video ref={videoRef} autoPlay muted playsInline className="video" />
            <canvas ref={overlayCanvasRef} className="overlay" />
          </div>
          <canvas ref={captureCanvasRef} className="hidden-canvas" />
          <div className="perception-meta">
            <div>found: {String(Boolean(perception?.found))}</div>
            <div>confidence: {Number(perception?.confidence || 0).toFixed(3)}</div>
            <div>offset_x: {Number(perception?.center_offset_x || 0).toFixed(1)}</div>
            <div>area: {Number(perception?.area || 0).toFixed(1)}</div>
          </div>
        </section>

        <section className="panel">
          <h2>Perception + State</h2>
          <pre>{JSON.stringify({ state: fsmState, perception, debug: lastDebug }, null, 2)}</pre>
        </section>

        <section className="panel">
          <h2>Last Plan</h2>
          <pre>{JSON.stringify(lastPlan, null, 2)}</pre>
        </section>
      </main>
    </div>
  );
}

export default App;
