#!/usr/bin/env python3
import argparse
import json
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline


@dataclass
class Row:
    instruction: str
    label_json: str


try:
    import cudf  # type: ignore
    from cuml.feature_extraction.text import TfidfVectorizer as CuTfidfVectorizer  # type: ignore
    from cuml.linear_model import LogisticRegression as CuLogisticRegression  # type: ignore

    HAS_RAPIDS = True
except Exception:
    HAS_RAPIDS = False
    cudf = None
    CuTfidfVectorizer = None
    CuLogisticRegression = None


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "to_numpy"):
        return np.asarray(value.to_numpy())
    if hasattr(value, "get"):
        return np.asarray(value.get())
    return np.asarray(value)


class ArtifactModel:
    def __init__(self, backend: str, model: Any, vectorizer: Any | None = None):
        self.backend = backend
        self.model = model
        self.vectorizer = vectorizer

    def _transform(self, texts: List[str]):
        if self.backend == "cpu":
            return texts
        if cudf is None or self.vectorizer is None:
            raise RuntimeError("gpu model runtime dependencies are missing")
        return self.vectorizer.transform(cudf.Series(texts))

    def predict(self, texts: List[str]) -> np.ndarray:
        if self.backend == "cpu":
            return self.model.predict(texts)
        pred = self.model.predict(self._transform(texts))
        return _to_numpy(pred)

    def predict_proba(self, texts: List[str]) -> np.ndarray:
        if self.backend == "cpu":
            return self.model.predict_proba(texts)
        probs = self.model.predict_proba(self._transform(texts))
        return _to_numpy(probs)


def _tiny_pretrain_specs() -> List[Tuple[str, Dict[str, Any]]]:
    speed = 0.55
    return [
        ("stop", {"task_type": "stop", "stop_kind": "normal", "canonical_actions": [{"type": "STOP"}]}),
        ("emergency stop now", {"task_type": "stop", "stop_kind": "emergency", "canonical_actions": [{"type": "STOP"}]}),
        ("abort mission", {"task_type": "stop", "stop_kind": "emergency", "canonical_actions": [{"type": "STOP"}]}),
        ("halt", {"task_type": "stop", "stop_kind": "normal", "canonical_actions": [{"type": "STOP"}]}),
        ("make a circle", {"task_type": "move-pattern", "pattern": "circle", "count": 1}),
        ("drive in a square", {"task_type": "move-pattern", "pattern": "square", "count": 1}),
        ("do two squares", {"task_type": "move-pattern", "pattern": "square", "count": 2}),
        ("move in a triangle", {"task_type": "move-pattern", "pattern": "triangle", "count": 1}),
        ("forward one meter", {"task_type": "move-pattern", "distance_m": 1.0, "count": 1, "canonical_actions": [{"type": "MOVE", "direction": "forward", "distance_m": 1.0, "speed": speed}]}),
        ("go forward 2 meters", {"task_type": "move-pattern", "distance_m": 2.0, "count": 1, "canonical_actions": [{"type": "MOVE", "direction": "forward", "distance_m": 2.0, "speed": speed}]}),
        ("move backward one meter", {"task_type": "move-pattern", "distance_m": 1.0, "count": 1, "canonical_actions": [{"type": "MOVE", "direction": "backward", "distance_m": 1.0, "speed": speed}]}),
        ("reverse half meter", {"task_type": "move-pattern", "distance_m": 0.5, "count": 1, "canonical_actions": [{"type": "MOVE", "direction": "backward", "distance_m": 0.5, "speed": speed}]}),
        ("strafe left one meter", {"task_type": "move-pattern", "distance_m": 1.0, "count": 1, "canonical_actions": [{"type": "MOVE", "direction": "left", "distance_m": 1.0, "speed": speed}]}),
        ("move left", {"task_type": "move-pattern", "distance_m": 1.0, "count": 1, "canonical_actions": [{"type": "MOVE", "direction": "left", "distance_m": 1.0, "speed": speed}]}),
        ("slide right", {"task_type": "move-pattern", "distance_m": 1.0, "count": 1, "canonical_actions": [{"type": "MOVE", "direction": "right", "distance_m": 1.0, "speed": speed}]}),
        ("move right 2 meters", {"task_type": "move-pattern", "distance_m": 2.0, "count": 1, "canonical_actions": [{"type": "MOVE", "direction": "right", "distance_m": 2.0, "speed": speed}]}),
        ("turn left", {"task_type": "move-pattern", "count": 1, "canonical_actions": [{"type": "TURN", "direction": "left", "angle_deg": 90, "speed": speed}]}),
        ("turn right", {"task_type": "move-pattern", "count": 1, "canonical_actions": [{"type": "TURN", "direction": "right", "angle_deg": 90, "speed": speed}]}),
        ("rotate clockwise", {"task_type": "move-pattern", "count": 1, "canonical_actions": [{"type": "TURN", "direction": "right", "angle_deg": 90, "speed": speed}]}),
        ("rotate counterclockwise", {"task_type": "move-pattern", "count": 1, "canonical_actions": [{"type": "TURN", "direction": "left", "angle_deg": 90, "speed": speed}]}),
        ("follow the person", {"task_type": "follow"}),
        ("follow red cube", {"task_type": "follow"}),
        ("search for banana", {"task_type": "search"}),
        ("search for blue box", {"task_type": "search"}),
        ("pick up the banana", {"task_type": "pick-object"}),
        ("grab the blue cube", {"task_type": "pick-object"}),
        ("avoid obstacles and approach the phone", {"task_type": "avoid+approach"}),
        ("approach while avoiding obstacles", {"task_type": "avoid+approach"}),
        ("go forward if there is no red obstacle", {"task_type": "move-if-clear", "distance_m": 1.0, "count": 1, "canonical_actions": [{"type": "MOVE", "direction": "forward", "distance_m": 1.0, "speed": speed}]}),
        ("move forward until red object appears", {"task_type": "move-if-clear", "distance_m": 1.0, "count": 1, "canonical_actions": [{"type": "MOVE", "direction": "forward", "distance_m": 1.0, "speed": speed}]}),
    ]


def tiny_pretrain_rows() -> List[Row]:
    rows: List[Row] = []
    for instruction, label in _tiny_pretrain_specs():
        label_json = json.dumps(label, sort_keys=True, separators=(",", ":"))
        rows.append(Row(instruction=instruction.strip().lower(), label_json=label_json))
    return rows


def load_rows(path: Path) -> List[Row]:
    rows: List[Row] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            instruction = payload.get("instruction")
            label = payload.get("label")
            if not isinstance(instruction, str) or not instruction.strip():
                continue
            if not isinstance(label, dict):
                continue
            label_json = json.dumps(label, sort_keys=True, separators=(",", ":"))
            rows.append(Row(instruction=instruction.strip().lower(), label_json=label_json))
    return rows


def _fit_gpu_model(x_train: List[str], y_train: List[str], seed: int) -> ArtifactModel:
    if not HAS_RAPIDS:
        raise RuntimeError("gpu backend requested, but RAPIDS cudf/cuml is not available")
    assert cudf is not None and CuTfidfVectorizer is not None and CuLogisticRegression is not None
    vectorizer = CuTfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    x_train_vec = vectorizer.fit_transform(cudf.Series(x_train))
    y_train_ser = cudf.Series(y_train)
    clf = CuLogisticRegression(max_iter=3000, random_state=seed)
    clf.fit(x_train_vec, y_train_ser)
    return ArtifactModel(backend="gpu", model=clf, vectorizer=vectorizer)


def _fit_cpu_model(x_train: List[str], y_train: List[str], seed: int) -> ArtifactModel:
    pipeline = Pipeline(
        steps=[
            ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)),
            (
                "clf",
                LogisticRegression(
                    max_iter=3000,
                    multi_class="multinomial",
                    solver="lbfgs",
                    random_state=seed
                ),
            ),
        ]
    )
    pipeline.fit(x_train, y_train)
    return ArtifactModel(backend="cpu", model=pipeline)


def train_model(rows: List[Row], seed: int, device: str) -> Tuple[ArtifactModel, Dict[str, Any]]:
    x = [row.instruction for row in rows]
    y = [row.label_json for row in rows]
    class_count = len(set(y))

    selected_backend = "cpu"
    if device == "gpu":
        selected_backend = "gpu"
    elif device == "auto" and HAS_RAPIDS:
        selected_backend = "gpu"

    if len(rows) < 20 or class_count < 2:
        model = _fit_gpu_model(x, y, seed) if selected_backend == "gpu" else _fit_cpu_model(x, y, seed)
        metrics = {
            "backend": model.backend,
            "train_size": len(rows),
            "test_size": 0,
            "train_accuracy": 1.0,
            "test_accuracy": None
        }
        return model, metrics

    stratify = y if min(y.count(label) for label in set(y)) >= 2 else None
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=seed, stratify=stratify
    )

    model = _fit_gpu_model(x_train, y_train, seed) if selected_backend == "gpu" else _fit_cpu_model(x_train, y_train, seed)
    train_pred = _to_numpy(model.predict(x_train))
    test_pred = _to_numpy(model.predict(x_test))
    metrics = {
        "backend": model.backend,
        "train_size": len(x_train),
        "test_size": len(x_test),
        "train_accuracy": round(float(accuracy_score(y_train, train_pred)), 4),
        "test_accuracy": round(float(accuracy_score(y_test, test_pred)), 4),
    }
    return model, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Train command parser model from JSONL dataset.")
    parser.add_argument("--dataset", type=Path, default=None, help="Dataset from extract_dataset.py")
    parser.add_argument(
        "--pretrain-small",
        action="store_true",
        help="Use built-in tiny pretraining corpus (good default for CLI bootstrap).",
    )
    parser.add_argument("--out", required=True, type=Path, help="Output artifact .pkl")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--device",
        choices=["auto", "cpu", "gpu"],
        default="auto",
        help="Training backend selection. gpu requires RAPIDS (cudf/cuml).",
    )
    args = parser.parse_args()

    rows: List[Row] = []
    if args.pretrain_small:
        rows.extend(tiny_pretrain_rows())
    if args.dataset is not None:
        rows.extend(load_rows(args.dataset))
    if not rows:
        raise SystemExit("no training rows found: provide --dataset and/or --pretrain-small")

    model, metrics = train_model(rows, args.seed, args.device)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    artifact = {
        "model": model,
        "metadata": {
            "created_at_utc": created_at,
            "dataset_path": str(args.dataset) if args.dataset is not None else None,
            "pretrain_small": bool(args.pretrain_small),
            "row_count": len(rows),
            "metrics": metrics,
            "device_requested": args.device,
            "version": f"command-model-{created_at.replace(':', '').replace('-', '').lower()}",
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("wb") as handle:
        pickle.dump(artifact, handle)

    print(f"saved_model={args.out}")
    print(json.dumps(artifact["metadata"], sort_keys=True))


if __name__ == "__main__":
    main()
