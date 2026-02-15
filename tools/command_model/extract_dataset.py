#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload


def _clean_label_from_parsed(parsed: Dict[str, Any]) -> Dict[str, Any] | None:
    task_type = parsed.get("task_type")
    if not isinstance(task_type, str) or not task_type:
        return None

    label: Dict[str, Any] = {"task_type": task_type}

    pattern = parsed.get("pattern")
    if isinstance(pattern, str) and pattern:
        label["pattern"] = pattern

    canonical_actions = parsed.get("canonical_actions")
    if isinstance(canonical_actions, list) and canonical_actions:
        label["canonical_actions"] = canonical_actions

    count = parsed.get("count")
    if isinstance(count, (int, float)):
        label["count"] = int(count)

    distance_m = parsed.get("distance_m")
    if isinstance(distance_m, (int, float)):
        label["distance_m"] = float(distance_m)

    return label


def _make_key(instruction: str, label: Dict[str, Any]) -> str:
    raw = json.dumps({"instruction": instruction, "label": label}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _extract_flat_parse_event(event: Dict[str, Any]) -> Tuple[str, Dict[str, Any]] | None:
    if event.get("event") != "vision_step.parse":
        return None
    instruction = event.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        return None
    parsed: Dict[str, Any] = {
        "task_type": event.get("parsed_task_type"),
        "pattern": event.get("parsed_pattern"),
        "canonical_actions": event.get("parsed_canonical_actions"),
    }
    return instruction.strip(), parsed


def _extract_nested_response_event(event: Dict[str, Any]) -> Tuple[str, Dict[str, Any]] | None:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    if payload.get("event") != "vision.step.response":
        return None
    body = payload.get("payload")
    if not isinstance(body, dict):
        return None
    debug = body.get("debug")
    if not isinstance(debug, dict):
        return None
    instruction = debug.get("applied_instruction")
    parsed = debug.get("parsed_instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        return None
    if not isinstance(parsed, dict):
        return None
    return instruction.strip(), parsed


def extract_examples(vision_trace: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for event in _iter_jsonl(vision_trace):
        extracted = _extract_flat_parse_event(event) or _extract_nested_response_event(event)
        if not extracted:
            continue
        instruction, parsed = extracted
        label = _clean_label_from_parsed(parsed)
        if not label:
            continue
        key = _make_key(instruction, label)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"instruction": instruction, "label": label})

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract command-model dataset from vision trace logs.")
    parser.add_argument("--vision-trace", required=True, type=Path, help="Path to logs/vision_trace.jsonl")
    parser.add_argument("--out", required=True, type=Path, help="Output JSONL file")
    args = parser.parse_args()

    examples = extract_examples(args.vision_trace)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with args.out.open("w", encoding="utf-8") as handle:
        for row in examples:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    counts: Dict[str, int] = {}
    for row in examples:
        task_type = row["label"]["task_type"]
        counts[task_type] = counts.get(task_type, 0) + 1

    print(f"wrote_examples={len(examples)} out={args.out}")
    print(f"task_type_counts={json.dumps(counts, sort_keys=True)}")


if __name__ == "__main__":
    main()
