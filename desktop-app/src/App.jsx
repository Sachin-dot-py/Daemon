import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import "./App.css";

const SERIAL_EVENT = "serial_line";
const OBSERVE_INTERVAL_MS = 1400;
const AUDIO_SAMPLE_INTERVAL_MS = 180;
const API_BASE_URL = (import.meta.env.VITE_DAEMON_API_BASE_URL || "http://localhost:3000").replace(/\/$/, "");

function parseManifestPayload(rawPayload) {
  const payload = rawPayload.trim();

  try {
    return JSON.parse(payload);
  } catch {
    // Continue to base64 fallback.
  }

  try {
    const decoded = atob(payload);
    return JSON.parse(decoded);
  } catch {
    return null;
  }
}

function scoreCommand(part, command) {
  const q = part.toLowerCase();
  let score = 0;

  const tokenWords = (command.token || "").toLowerCase().split("_");
  if (tokenWords.every((word) => q.includes(word))) {
    score += 5;
  }

  if ((command.desc || "").toLowerCase().split(" ").some((word) => word && q.includes(word))) {
    score += 3;
  }

  const synonyms = command.nlp?.synonyms || [];
  for (const synonym of synonyms) {
    if (q.includes(String(synonym).toLowerCase())) {
      score += 4;
    }
  }

  return score;
}

function extractNumbers(text) {
  const matches = text.match(/-?\d+(?:\.\d+)?/g);
  return matches ? matches.map((piece) => Number(piece)) : [];
}

function planCommands(prompt, manifest) {
  const commands = manifest?.commands || [];
  if (!commands.length) {
    return [];
  }

  const normalized = prompt.trim().toLowerCase();
  if (!normalized) {
    return [];
  }

  if (normalized.includes("stop")) {
    return [{ token: "STOP", args: [] }];
  }

  const parts = normalized.split(/\bthen\b|\band then\b|,/).map((part) => part.trim()).filter(Boolean);
  const numbers = extractNumbers(normalized);
  let numberIndex = 0;

  const plan = [];
  for (const part of parts) {
    let best = null;
    for (const command of commands) {
      const score = scoreCommand(part, command);
      if (score > 0 && (!best || score > best.score)) {
        best = { command, score };
      }
    }

    if (!best) {
      continue;
    }

    const args = [];
    for (const arg of best.command.args || []) {
      if (numberIndex < numbers.length) {
        args.push(numbers[numberIndex]);
        numberIndex += 1;
      } else if (arg.min !== null && arg.min !== undefined) {
        args.push(arg.min);
      } else {
        args.push(0);
      }
    }

    plan.push({ token: best.command.token, args });
  }

  return plan;
}

function extractDurationMs(text, defaultDurationMs) {
  const durationMatch = text.match(/(\d+(?:\.\d+)?)\s*(ms|millisecond|milliseconds|s|sec|second|seconds)?\b/i);
  if (!durationMatch) {
    return defaultDurationMs;
  }

  const value = Number(durationMatch[1]);
  if (!Number.isFinite(value) || value <= 0) {
    return defaultDurationMs;
  }

  const unit = (durationMatch[2] || "ms").toLowerCase();
  if (unit === "s" || unit === "sec" || unit === "second" || unit === "seconds") {
    return Math.round(value * 1000);
  }

  return Math.round(value);
}

function planMecanumCommands(prompt, defaultDurationMs) {
  const normalized = prompt.trim().toLowerCase();
  if (!normalized) {
    return [];
  }

  const parts = normalized.split(/\bthen\b|\band then\b|,/).map((part) => part.trim()).filter(Boolean);
  const plan = [];

  for (const part of parts) {
    if (part.includes("stop")) {
      plan.push({ command: "S", durationMs: 0 });
      continue;
    }

    if (part.includes("rotate left") || part.includes("turn left") || part.includes("spin left")) {
      plan.push({ command: "Q", durationMs: extractDurationMs(part, defaultDurationMs) });
      continue;
    }

    if (part.includes("rotate right") || part.includes("turn right") || part.includes("spin right")) {
      plan.push({ command: "E", durationMs: extractDurationMs(part, defaultDurationMs) });
      continue;
    }

    if (part.includes("strafe left") || part.includes("slide left")) {
      plan.push({ command: "L", durationMs: extractDurationMs(part, defaultDurationMs) });
      continue;
    }

    if (part.includes("strafe right") || part.includes("slide right")) {
      plan.push({ command: "R", durationMs: extractDurationMs(part, defaultDurationMs) });
      continue;
    }

    if (part.includes("back") || part.includes("reverse")) {
      plan.push({ command: "B", durationMs: extractDurationMs(part, defaultDurationMs) });
      continue;
    }

    if (part.includes("forward") || part.includes("ahead")) {
      plan.push({ command: "F", durationMs: extractDurationMs(part, defaultDurationMs) });
    }
  }

  return plan;
}

function safeTrimmedTail(items, size) {
  return (items || []).slice(-size).map((entry) => String(entry));
}

function formatConfidence(confidence) {
  if (typeof confidence !== "number" || Number.isNaN(confidence)) {
    return "--";
  }
  return `${Math.round(confidence * 100)}%`;
}

function App() {
  const [ports, setPorts] = useState([]);
  const [selectedPort, setSelectedPort] = useState("");
  const [connectedPort, setConnectedPort] = useState("");
  const [manifest, setManifest] = useState(null);
  const [telemetry, setTelemetry] = useState([]);
  const [wireLog, setWireLog] = useState([]);
  const [chat, setChat] = useState([]);
  const [draft, setDraft] = useState("");
  const [errorText, setErrorText] = useState("");
  const [busy, setBusy] = useState(false);

  const [modelCode, setModelCode] = useState("");
  const [expectedOutcome, setExpectedOutcome] = useState("");
  const [testBusy, setTestBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [mediaReady, setMediaReady] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [decision, setDecision] = useState("UNSURE");
  const [confidence, setConfidence] = useState(null);
  const [statusMessage, setStatusMessage] = useState("Waiting to start.");
  const [suggestedCode, setSuggestedCode] = useState("");
  const [patchSummary, setPatchSummary] = useState("");
  const [evalHistory, setEvalHistory] = useState([]);
  const [bridgeHost, setBridgeHost] = useState("vporto26.local");
  const [bridgePort, setBridgePort] = useState("8765");
  const [bridgeToken, setBridgeToken] = useState("treehacks");
  const [bridgeMoveMs, setBridgeMoveMs] = useState("500");
  const [bridgeBusy, setBridgeBusy] = useState(false);
  const [bridgeStatus, setBridgeStatus] = useState("idle");
  const [bridgeConnected, setBridgeConnected] = useState(false);
  const [controlMode, setControlMode] = useState("pi");

  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const audioDataRef = useRef(null);
  const observeTimerRef = useRef(null);
  const audioTimerRef = useRef(null);
  const rmsRef = useRef(0);
  const sessionIdRef = useRef("");
  const observeInFlightRef = useRef(false);

  const catalog = useMemo(() => manifest?.commands || [], [manifest]);

  const pushLog = (line) => {
    setWireLog((prev) => [...prev.slice(-199), line]);
  };

  const pushEvalHistory = (entry) => {
    setEvalHistory((prev) => [
      ...prev.slice(-49),
      {
        at: new Date().toLocaleTimeString(),
        decision: entry.decision,
        confidence: entry.confidence,
        message: entry.message
      }
    ]);
  };

  const parseBridgePort = () => {
    const value = Number.parseInt(bridgePort, 10);
    if (!Number.isFinite(value) || value < 1 || value > 65535) {
      return 8765;
    }
    return value;
  };

  const parseBridgeMoveMs = () => {
    const value = Number.parseInt(bridgeMoveMs, 10);
    if (!Number.isFinite(value) || value < 0 || value > 10000) {
      return 500;
    }
    return value;
  };

  const sendMecanumCommand = async (command, overrideDurationMs) => {
    setBridgeBusy(true);
    try {
      const durationMs = overrideDurationMs ?? parseBridgeMoveMs();
      const result = await invoke("send_mecanum_via_pi_bridge", {
        // Backend will reuse persistent connection if already established.
        host: bridgeHost.trim(),
        port: parseBridgePort(),
        token: bridgeToken.trim(),
        command,
        durationMs
      });

      setBridgeStatus(`sent ${result.command} (${result.durationMs}ms) to ${result.target}`);
      setBridgeConnected(true);
      pushLog(`PI ${result.target} ${result.command} ${result.durationMs}ms`);
      setErrorText("");
      return true;
    } catch (error) {
      const message = String(error);
      setErrorText(message);
      setBridgeStatus(`dispatch failed: ${message}`);
      setBridgeConnected(false);
      pushLog(`PI ERR ${message}`);
      return false;
    } finally {
      setBridgeBusy(false);
    }
  };

  const connectBridge = async () => {
    setBridgeBusy(true);
    try {
      const status = await invoke("connect_pi_bridge", {
        host: bridgeHost.trim(),
        port: parseBridgePort(),
        token: bridgeToken.trim()
      });
      setBridgeConnected(Boolean(status.connected));
      setBridgeStatus(status.connected ? `connected to ${status.target}` : "disconnected");
      pushLog(`PI CONNECT ${status.target || ""}`.trim());
      setErrorText("");
    } catch (error) {
      const message = String(error);
      setBridgeConnected(false);
      setBridgeStatus(`connect failed: ${message}`);
      setErrorText(message);
      pushLog(`PI CONNECT_ERR ${message}`);
    } finally {
      setBridgeBusy(false);
    }
  };

  const disconnectBridge = async () => {
    setBridgeBusy(true);
    try {
      await invoke("disconnect_pi_bridge");
      setBridgeConnected(false);
      setBridgeStatus("disconnected");
      pushLog("PI DISCONNECT");
      setErrorText("");
    } catch (error) {
      const message = String(error);
      setBridgeStatus(`disconnect failed: ${message}`);
      setErrorText(message);
      pushLog(`PI DISCONNECT_ERR ${message}`);
    } finally {
      setBridgeBusy(false);
    }
  };

  const callRealtimeApi = async (payload) => {
    const response = await fetch(`${API_BASE_URL}/api/realtime/evaluate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const message = body?.message || `Realtime API request failed (${response.status})`;
      throw new Error(message);
    }

    return body;
  };

  const callMecanumPlannerApi = async (instruction) => {
    const response = await fetch(`${API_BASE_URL}/api/mecanum/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        instruction,
        default_duration_ms: parseBridgeMoveMs(),
        max_steps: 28
      })
    });

    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const message = body?.message || `Mecanum planner request failed (${response.status})`;
      throw new Error(message);
    }
    return body;
  };

  const captureFrame = () => {
    const videoEl = videoRef.current;
    const canvasEl = canvasRef.current;
    if (!videoEl || !canvasEl || videoEl.readyState < 2) {
      return "";
    }

    const width = 320;
    const height = 180;
    canvasEl.width = width;
    canvasEl.height = height;
    const ctx = canvasEl.getContext("2d");
    if (!ctx) {
      return "";
    }

    ctx.drawImage(videoEl, 0, 0, width, height);
    const encoded = canvasEl.toDataURL("image/jpeg", 0.6);
    const [, base64 = ""] = encoded.split(",");
    return base64;
  };

  const stopMediaCapture = async () => {
    if (audioTimerRef.current) {
      window.clearInterval(audioTimerRef.current);
      audioTimerRef.current = null;
    }

    if (audioContextRef.current) {
      try {
        await audioContextRef.current.close();
      } catch {
        // Ignore close failure.
      }
      audioContextRef.current = null;
    }

    analyserRef.current = null;
    audioDataRef.current = null;
    rmsRef.current = 0;

    if (streamRef.current) {
      for (const track of streamRef.current.getTracks()) {
        track.stop();
      }
      streamRef.current = null;
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    setMediaReady(false);
  };

  const startMediaCapture = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 360, frameRate: { ideal: 24 } },
      audio: true
    });

    streamRef.current = stream;

    if (videoRef.current) {
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
    }

    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (AudioCtx) {
      const audioContext = new AudioCtx();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);

      const data = new Uint8Array(analyser.fftSize);
      audioContextRef.current = audioContext;
      analyserRef.current = analyser;
      audioDataRef.current = data;

      audioTimerRef.current = window.setInterval(() => {
        if (!analyserRef.current || !audioDataRef.current) {
          return;
        }

        analyserRef.current.getByteTimeDomainData(audioDataRef.current);
        let sum = 0;
        for (let i = 0; i < audioDataRef.current.length; i += 1) {
          const centered = (audioDataRef.current[i] - 128) / 128;
          sum += centered * centered;
        }
        const rms = Math.sqrt(sum / audioDataRef.current.length);
        rmsRef.current = Math.max(0, Math.min(1, rms));
      }, AUDIO_SAMPLE_INTERVAL_MS);
    }

    setMediaReady(true);
  };

  const clearObserveLoop = () => {
    if (observeTimerRef.current) {
      window.clearInterval(observeTimerRef.current);
      observeTimerRef.current = null;
    }
  };

  const stopRealtimeCycle = async (reason) => {
    clearObserveLoop();
    setTesting(false);
    observeInFlightRef.current = false;

    const currentSessionId = sessionIdRef.current;
    sessionIdRef.current = "";
    setSessionId("");

    if (currentSessionId) {
      try {
        await callRealtimeApi({
          event: "stop",
          session_id: currentSessionId,
          expected_outcome: expectedOutcome.trim(),
          current_code: modelCode.trim(),
          telemetry_tail: safeTrimmedTail(telemetry, 12)
        });
      } catch {
        // Ignore stop errors.
      }
    }

    await stopMediaCapture();

    if (reason) {
      setChat((prev) => [...prev, { role: "assistant", content: reason }]);
    }
  };

  const observeOnce = async () => {
    if (!sessionIdRef.current || observeInFlightRef.current) {
      return;
    }

    observeInFlightRef.current = true;
    try {
      const response = await callRealtimeApi({
        event: "observe",
        session_id: sessionIdRef.current,
        expected_outcome: expectedOutcome.trim(),
        current_code: modelCode.trim(),
        telemetry_tail: safeTrimmedTail(telemetry, 12),
        observation: {
          timestamp_ms: Date.now(),
          audio_rms: rmsRef.current,
          video_frame_jpeg_base64: captureFrame()
        }
      });

      setDecision(response.decision);
      setConfidence(response.confidence);
      setStatusMessage(response.message);
      pushEvalHistory(response);

      if (response.should_update_code && response.updated_code) {
        setSuggestedCode(response.updated_code);
        setPatchSummary(response.patch_summary || "Model suggested a code update.");
      }

      if (response.decision === "MATCH") {
        await stopRealtimeCycle("Realtime evaluator confirmed expected behavior.");
      } else if (response.should_update_code && response.updated_code) {
        await stopRealtimeCycle("Realtime evaluator proposed a code update. Apply it and run test again.");
      }
    } catch (error) {
      setErrorText(String(error));
      await stopRealtimeCycle("Realtime loop stopped due to evaluator/API error.");
    } finally {
      observeInFlightRef.current = false;
    }
  };

  const beginObserveLoop = () => {
    clearObserveLoop();
    observeTimerRef.current = window.setInterval(() => {
      observeOnce();
    }, OBSERVE_INTERVAL_MS);
    observeOnce();
  };

  const refreshPorts = async () => {
    try {
      const result = await invoke("list_serial_ports");
      setPorts(result);
      if (!selectedPort && result.length > 0) {
        setSelectedPort(result[0].portName);
      }
      setErrorText("");
    } catch (error) {
      setErrorText(String(error));
    }
  };

  useEffect(() => {
    refreshPorts();

    let unlisten;
    listen(SERIAL_EVENT, (event) => {
      const line = String(event.payload || "").trim();
      if (!line) {
        return;
      }

      pushLog(line);

      if (line.startsWith("MANIFEST ")) {
        const payload = line.slice("MANIFEST ".length);
        const parsed = parseManifestPayload(payload);
        if (parsed && Array.isArray(parsed.commands)) {
          setManifest(parsed);
          setChat((prev) => [...prev, { role: "assistant", content: `Manifest loaded (${parsed.commands.length} commands).` }]);
        } else {
          setChat((prev) => [...prev, { role: "assistant", content: "Manifest payload could not be parsed." }]);
        }
      } else if (line.startsWith("TELEMETRY ")) {
        setTelemetry((prev) => [...prev.slice(-99), line.slice("TELEMETRY ".length)]);
      } else if (line.startsWith("ERR ")) {
        setChat((prev) => [...prev, { role: "assistant", content: `Device error: ${line}` }]);
      }
    }).then((cleanup) => {
      unlisten = cleanup;
    });

    invoke("get_connection_status")
      .then((status) => {
        if (status.connected && status.portName) {
          setConnectedPort(status.portName);
        }
      })
      .catch(() => {});

    invoke("get_pi_bridge_status")
      .then((status) => {
        setBridgeConnected(Boolean(status.connected));
        if (status.connected && status.target) {
          setBridgeStatus(`connected to ${status.target}`);
        }
      })
      .catch(() => {});

    return () => {
      clearObserveLoop();
      stopMediaCapture();
      if (unlisten) {
        unlisten();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const connect = async () => {
    if (!selectedPort) {
      setErrorText("Select a serial port first.");
      return;
    }

    setBusy(true);
    try {
      const status = await invoke("connect_serial", { portName: selectedPort, baudRate: 115200 });
      if (status.connected) {
        setConnectedPort(status.portName || selectedPort);
        setManifest(null);
        setTelemetry([]);
        setWireLog([]);
        await invoke("send_serial_line", { line: "HELLO" });
        await invoke("send_serial_line", { line: "READ_MANIFEST" });
        setChat((prev) => [...prev, { role: "assistant", content: `Connected to ${selectedPort}. Requested manifest.` }]);
      }
      setErrorText("");
    } catch (error) {
      setErrorText(String(error));
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    try {
      await invoke("disconnect_serial");
      setConnectedPort("");
      setManifest(null);
      setTelemetry([]);
      setErrorText("");
      await stopRealtimeCycle("Device disconnected; stopped realtime loop.");
    } catch (error) {
      setErrorText(String(error));
    } finally {
      setBusy(false);
    }
  };

  const sendInstruction = async () => {
    const prompt = draft.trim();
    if (!prompt) {
      return;
    }

    setChat((prev) => [...prev, { role: "user", content: prompt }]);
    setDraft("");

    if (controlMode === "serial") {
      if (!connectedPort) {
        setChat((prev) => [...prev, { role: "assistant", content: "Serial mode selected, but no serial device is connected." }]);
        return;
      }

      const plan = planCommands(prompt, manifest);

      if (!plan.length) {
        setChat((prev) => [...prev, { role: "assistant", content: "No matching command found in manifest catalog." }]);
        return;
      }

      const planText = plan.map((step) => `RUN ${step.token}${step.args.length ? ` ${step.args.join(" ")}` : ""}`).join(" | ");
      const codeBlock = `${plan.map((step) => `RUN ${step.token}${step.args.length ? ` ${step.args.join(" ")}` : ""}`).join("\n")}\nSTOP`;
      setModelCode(codeBlock);
      setChat((prev) => [...prev, { role: "assistant", content: `Plan: ${planText}` }]);

      for (const step of plan) {
        try {
          if (step.token === "STOP") {
            await invoke("send_serial_line", { line: "STOP" });
          } else {
            const line = `RUN ${step.token}${step.args.length ? ` ${step.args.join(" ")}` : ""}`;
            await invoke("send_serial_line", { line });
          }
        } catch (error) {
          setChat((prev) => [...prev, { role: "assistant", content: `Send failed: ${String(error)}` }]);
        }
      }
      return;
    }

    const mecanumPlan = planMecanumCommands(prompt, parseBridgeMoveMs());
    if (!mecanumPlan.length) {
      try {
        setChat((prev) => [...prev, { role: "assistant", content: "Planning with model..." }]);
        const planned = await callMecanumPlannerApi(prompt);
        const steps = Array.isArray(planned?.plan) ? planned.plan : [];
        const explanation = typeof planned?.explanation === "string" ? planned.explanation : "Planned motion.";

        const normalized = steps
          .map((step) => ({
            command: String(step?.cmd || "").trim().toUpperCase(),
            durationMs: Number(step?.duration_ms)
          }))
          .filter((step) => ["F", "B", "L", "R", "Q", "E", "S"].includes(step.command) && Number.isFinite(step.durationMs));

        if (!normalized.length) {
          setChat((prev) => [...prev, { role: "assistant", content: "Planner returned no valid steps." }]);
          return;
        }

        setChat((prev) => [...prev, { role: "assistant", content: `Pi plan: ${explanation}` }]);
        for (const step of normalized) {
          const sent = await sendMecanumCommand(step.command, step.durationMs);
          if (!sent) {
            setChat((prev) => [...prev, { role: "assistant", content: `Pi command ${step.command} failed.` }]);
            break;
          }
        }
        return;
      } catch (error) {
        setChat((prev) => [...prev, { role: "assistant", content: `Planner failed: ${String(error)}` }]);
        return;
      }
    }

    const summary = mecanumPlan.map((step) => `${step.command}${step.durationMs ? `(${step.durationMs}ms)` : ""}`).join(" -> ");
    setChat((prev) => [...prev, { role: "assistant", content: `Pi plan: ${summary}` }]);

    for (const step of mecanumPlan) {
      const sent = await sendMecanumCommand(step.command, step.durationMs);
      if (!sent) {
        setChat((prev) => [...prev, { role: "assistant", content: `Pi command ${step.command} failed.` }]);
        break;
      }
    }
  };

  const startRealtimeTest = async () => {
    if (!connectedPort) {
      setErrorText("Connect to a device before starting realtime test.");
      return;
    }

    if (!modelCode.trim()) {
      setErrorText("Model output code is required.");
      return;
    }

    if (!expectedOutcome.trim()) {
      setErrorText("Expected outcome is required.");
      return;
    }

    setTestBusy(true);
    setErrorText("");
    setSuggestedCode("");
    setPatchSummary("");
    setEvalHistory([]);
    setDecision("UNSURE");
    setConfidence(null);
    setStatusMessage("Deploying code to device...");

    try {
      const deployedLines = await invoke("deploy_code_to_device", { code: modelCode });
      setChat((prev) => [
        ...prev,
        { role: "assistant", content: `Uploaded ${deployedLines} code lines to ${connectedPort}. Starting webcam/mic validation.` }
      ]);

      await startMediaCapture();

      const startResponse = await callRealtimeApi({
        event: "start",
        expected_outcome: expectedOutcome.trim(),
        current_code: modelCode.trim(),
        telemetry_tail: safeTrimmedTail(telemetry, 12)
      });

      sessionIdRef.current = startResponse.session_id;
      setSessionId(startResponse.session_id);
      setDecision(startResponse.decision);
      setConfidence(startResponse.confidence);
      setStatusMessage(startResponse.message);
      pushEvalHistory(startResponse);
      setTesting(true);
      beginObserveLoop();
    } catch (error) {
      setErrorText(String(error));
      await stopRealtimeCycle("Failed to start realtime cycle.");
    } finally {
      setTestBusy(false);
    }
  };

  const applySuggestedCode = () => {
    if (!suggestedCode) {
      return;
    }
    setModelCode(suggestedCode);
    setChat((prev) => [...prev, { role: "assistant", content: "Applied suggested code update. Run Test on Device again." }]);
  };

  return (
    <div className="app">
      <header className="topbar">
        <h1>DAEMON Desktop</h1>
        <div className="connect-row">
          <select value={selectedPort} onChange={(event) => setSelectedPort(event.target.value)}>
            {ports.map((port) => (
              <option key={port.portName} value={port.portName}>
                {port.portName} ({port.portType})
              </option>
            ))}
            {!ports.length && <option value="">No serial ports</option>}
          </select>
          <button onClick={refreshPorts} disabled={busy}>Refresh</button>
          {!connectedPort && <button onClick={connect} disabled={busy || !selectedPort}>Connect</button>}
          {connectedPort && <button onClick={disconnect} disabled={busy}>Disconnect</button>}
        </div>
      </header>

      <div className="status-row">
        <span>{connectedPort ? `Connected: ${connectedPort}` : "Disconnected"}</span>
        <span>Realtime API: {API_BASE_URL}</span>
        {errorText && <span className="error">{errorText}</span>}
      </div>

      <main className="grid">
        <section className="panel chat-panel">
          <h2>Chat</h2>
          <div className="chat-log">
            {chat.map((message, idx) => (
              <div key={`${message.role}-${idx}`} className={`msg ${message.role}`}>
                <strong>{message.role === "user" ? "You" : "Agent"}:</strong> {message.content}
              </div>
            ))}
            {!chat.length && <div className="empty">Send a natural language command for serial manifest mode or Pi mecanum mode.</div>}
          </div>
          <div className="composer">
            <select value={controlMode} onChange={(event) => setControlMode(event.target.value)}>
              <option value="pi">Pi Bridge Mode</option>
              <option value="serial">Serial Device Mode</option>
            </select>
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Example: go forward 30 then turn left 90"
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  sendInstruction();
                }
              }}
            />
            <button onClick={sendInstruction} disabled={controlMode === "pi" ? bridgeBusy : !connectedPort}>Send</button>
            <button
              onClick={() => {
                if (controlMode === "serial" && connectedPort) {
                  invoke("send_serial_line", { line: "STOP" });
                } else {
                  sendMecanumCommand("S", 0);
                }
              }}
              disabled={controlMode === "pi" ? bridgeBusy : !connectedPort}
            >
              STOP
            </button>
          </div>

          <div className="bridge-box">
            <h3>Pi Mecanum Bridge</h3>
            <div className="bridge-config">
              <input value={bridgeHost} onChange={(event) => setBridgeHost(event.target.value)} placeholder="pi host (prefer IP)" />
              <input value={bridgePort} onChange={(event) => setBridgePort(event.target.value)} placeholder="bridge port" />
              <input value={bridgeToken} onChange={(event) => setBridgeToken(event.target.value)} placeholder="bridge token" />
              <input value={bridgeMoveMs} onChange={(event) => setBridgeMoveMs(event.target.value)} placeholder="move ms" />
            </div>
            <div className="bridge-pad">
              {!bridgeConnected && <button onClick={connectBridge} disabled={bridgeBusy}>Connect Bridge</button>}
              {bridgeConnected && <button onClick={disconnectBridge} disabled={bridgeBusy}>Disconnect Bridge</button>}
            </div>
            <div className="bridge-pad">
              <button onClick={() => sendMecanumCommand("F")} disabled={bridgeBusy}>Forward (F)</button>
              <button onClick={() => sendMecanumCommand("B")} disabled={bridgeBusy}>Backward (B)</button>
              <button onClick={() => sendMecanumCommand("L")} disabled={bridgeBusy}>Strafe Left (L)</button>
              <button onClick={() => sendMecanumCommand("R")} disabled={bridgeBusy}>Strafe Right (R)</button>
              <button onClick={() => sendMecanumCommand("Q")} disabled={bridgeBusy}>Rotate Left (Q)</button>
              <button onClick={() => sendMecanumCommand("E")} disabled={bridgeBusy}>Rotate Right (E)</button>
              <button onClick={() => sendMecanumCommand("S", 0)} disabled={bridgeBusy}>Stop (S)</button>
            </div>
            <div className="bridge-status">Bridge: {bridgeBusy ? "working..." : bridgeStatus}</div>
          </div>
        </section>

        <section className="panel test-panel">
          <h2>Realtime Test on Device</h2>
          <label className="field">
            <span>Model output code</span>
            <textarea
              rows={8}
              value={modelCode}
              onChange={(event) => setModelCode(event.target.value)}
              placeholder="Paste generated code or command script here."
            />
          </label>
          <label className="field">
            <span>Expected outcome</span>
            <input
              value={expectedOutcome}
              onChange={(event) => setExpectedOutcome(event.target.value)}
              placeholder="Example: Robot moves forward 30cm then stops."
            />
          </label>
          <div className="test-controls">
            <button onClick={startRealtimeTest} disabled={testBusy || testing || !connectedPort}>Test on Device</button>
            <button onClick={() => stopRealtimeCycle("Realtime cycle stopped by user.")} disabled={!testing}>Stop Test</button>
            <button onClick={applySuggestedCode} disabled={!suggestedCode}>Apply Code Update</button>
          </div>

          <div className="decision-card">
            <div><strong>Session:</strong> {sessionId || "not started"}</div>
            <div><strong>State:</strong> {testing ? "Monitoring" : "Idle"} ({mediaReady ? "webcam/mic on" : "media off"})</div>
            <div><strong>Decision:</strong> {decision}</div>
            <div><strong>Confidence:</strong> {formatConfidence(confidence)}</div>
            <div><strong>Model message:</strong> {statusMessage}</div>
            {patchSummary && <div><strong>Patch summary:</strong> {patchSummary}</div>}
          </div>

          <div className="video-wrap">
            <video ref={videoRef} autoPlay muted playsInline />
            <canvas ref={canvasRef} className="hidden-canvas" />
          </div>

          <div className="eval-log">
            {evalHistory.map((entry, idx) => (
              <div key={`${entry.at}-${idx}`}>
                {entry.at} | {entry.decision} ({formatConfidence(entry.confidence)}): {entry.message}
              </div>
            ))}
            {!evalHistory.length && <div className="empty">No evaluation events yet.</div>}
          </div>
        </section>

        <section className="panel manifest-panel">
          <h2>Manifest</h2>
          <div className="manifest-list">
            {catalog.map((cmd) => (
              <div key={cmd.token} className="cmd-card">
                <div className="cmd-token">{cmd.token}</div>
                <div className="cmd-desc">{cmd.desc}</div>
                <div className="cmd-args">
                  {(cmd.args || []).length
                    ? cmd.args.map((arg) => `${arg.name}:${arg.type}`).join(", ")
                    : "No args"}
                </div>
              </div>
            ))}
            {!catalog.length && <div className="empty">Manifest not loaded.</div>}
          </div>
        </section>

        <section className="panel telemetry-panel">
          <h2>Telemetry</h2>
          <div className="telemetry-log">
            {telemetry.map((line, idx) => (
              <div key={`${line}-${idx}`}>{line}</div>
            ))}
            {!telemetry.length && <div className="empty">No telemetry yet.</div>}
          </div>
        </section>

        <section className="panel wire-panel">
          <h2>Wire Log</h2>
          <div className="wire-log">
            {wireLog.map((line, idx) => (
              <div key={`${line}-${idx}`}>{line}</div>
            ))}
            {!wireLog.length && <div className="empty">No serial messages yet.</div>}
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
