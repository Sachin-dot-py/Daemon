#!/usr/bin/env python3
import argparse
import json
import pickle
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple


def _load_artifact(path: Path) -> Tuple[Any, Dict[str, Any]]:
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict) or "model" not in payload:
        raise RuntimeError("invalid model artifact")
    model = payload["model"]
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return model, metadata


class Handler(BaseHTTPRequestHandler):
    model = None
    model_version = "command-model-unknown"
    api_key = ""

    def _write_json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any] | None:
        raw_len = self.headers.get("Content-Length")
        if not raw_len:
            return None
        try:
            length = int(raw_len)
        except ValueError:
            return None
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def do_POST(self) -> None:
        if self.path not in ("/predict", "/"):
            self._write_json(404, {"error": "not_found"})
            return

        if self.api_key:
            auth = self.headers.get("Authorization") or ""
            expected = f"Bearer {self.api_key}"
            if auth.strip() != expected:
                self._write_json(401, {"error": "unauthorized"})
                return

        payload = self._read_json()
        if payload is None:
            self._write_json(400, {"error": "bad_json"})
            return

        instruction = payload.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            self._write_json(400, {"error": "instruction_required"})
            return

        text = instruction.strip().lower()
        predicted_label = self.model.predict([text])[0]
        if not isinstance(predicted_label, str):
            predicted_label = str(predicted_label)
        confidence = 0.0
        if hasattr(self.model, "predict_proba"):
            probs = self.model.predict_proba([text])[0]
            confidence = float(max(probs)) if len(probs) else 0.0

        try:
            prediction = json.loads(predicted_label)
        except json.JSONDecodeError:
            self._write_json(500, {"error": "invalid_prediction_payload"})
            return

        self._write_json(
            200,
            {
                "prediction": prediction,
                "confidence": round(confidence, 4),
                "model_version": self.model_version,
            },
        )

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json(200, {"ok": True, "model_version": self.model_version})
            return
        self._write_json(404, {"error": "not_found"})

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve command parser model via HTTP.")
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--api-key", default="", help="Optional Bearer token for requests")
    args = parser.parse_args()

    model, metadata = _load_artifact(args.model)
    version = str(metadata.get("version") or f"command-model-{args.model.stat().st_mtime_ns}")

    Handler.model = model
    Handler.model_version = version
    Handler.api_key = args.api_key.strip()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"listening=http://{args.host}:{args.port} model_version={version}")
    server.serve_forever()


if __name__ == "__main__":
    main()
