#!/usr/bin/env python3
import argparse
import json
import pickle
from pathlib import Path
from typing import Any, Dict, Tuple


def load_artifact(path: Path) -> Tuple[Any, Dict[str, Any]]:
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict) or "model" not in payload:
        raise RuntimeError("invalid model artifact")
    model = payload["model"]
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return model, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI inference for command parser model artifact.")
    parser.add_argument("--model", required=True, type=Path, help="Path to .pkl artifact")
    parser.add_argument("--instruction", required=True, help="Instruction to classify")
    args = parser.parse_args()

    model, metadata = load_artifact(args.model)
    text = args.instruction.strip().lower()
    if not text:
        raise SystemExit("instruction cannot be empty")

    predicted_label = model.predict([text])[0]
    if not isinstance(predicted_label, str):
        predicted_label = str(predicted_label)
    confidence = 0.0
    if hasattr(model, "predict_proba"):
        probs = model.predict_proba([text])[0]
        confidence = float(max(probs)) if len(probs) else 0.0

    prediction = json.loads(predicted_label)
    print(
        json.dumps(
            {
                "prediction": prediction,
                "confidence": round(confidence, 4),
                "model_version": metadata.get("version"),
            },
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
