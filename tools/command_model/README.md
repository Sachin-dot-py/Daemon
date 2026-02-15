# Command Model (DGX-ready)

This folder contains a minimal training and inference path for a command parser model that predicts DAEMON canonical actions from natural-language instructions.

It is designed to integrate with:
- `vercel-api/src/app/api/vision_step/route.ts`
- `DAEMON_COMMAND_MODEL_*` env flags (disabled by default)

## 1) Install deps

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tools/command_model/requirements.txt
```

## 2) Build dataset from trace logs

```bash
python3 tools/command_model/extract_dataset.py \
  --vision-trace logs/vision_trace.jsonl \
  --out tools/command_model/data/train.jsonl
```

## 3) Train model

```bash
python3 tools/command_model/train_command_model.py \
  --dataset tools/command_model/data/train.jsonl \
  --out tools/command_model/artifacts/command_model.pkl
```

Backend options:
- `--device auto` (default): use GPU when RAPIDS is available, otherwise CPU
- `--device cpu`: force CPU (`scikit-learn`)
- `--device gpu`: require RAPIDS (`cudf` + `cuml`) and fail fast if missing

## 3b) Pretrain a tiny model for CLI usage (no logs required)

```bash
python3 tools/command_model/train_command_model.py \
  --pretrain-small \
  --device auto \
  --out tools/command_model/artifacts/command_model_tiny.pkl
```

You can also combine both:

```bash
python3 tools/command_model/train_command_model.py \
  --pretrain-small \
  --dataset tools/command_model/data/train.jsonl \
  --device auto \
  --out tools/command_model/artifacts/command_model.pkl
```

GPU note:
- `requirements.txt` installs CPU deps only.
- For GPU training/inference, install RAPIDS in your Spark image/environment (matching your CUDA version), then run with `--device gpu` or `--device auto`.

## 4) Serve model

```bash
python3 tools/command_model/serve_command_model.py \
  --model tools/command_model/artifacts/command_model.pkl \
  --host 0.0.0.0 \
  --port 8787
```

Request:

```json
{ "instruction": "move left 1 meter" }
```

Response:

```json
{
  "prediction": {
    "task_type": "move-pattern",
    "canonical_actions": [{ "type": "MOVE", "direction": "left", "distance_m": 1.0 }]
  },
  "confidence": 0.91,
  "model_version": "command-model-20260215"
}
```

## 4b) Use artifact directly from CLI (no HTTP server)

```bash
python3 tools/command_model/predict_command_model.py \
  --model tools/command_model/artifacts/command_model_tiny.pkl \
  --instruction "move left one meter"
```

## 5) Wire into `vercel-api` (optional)

Set in `vercel-api/.env.local`:

```bash
DAEMON_COMMAND_MODEL_ENABLED=false
DAEMON_COMMAND_MODEL_SHADOW=true
DAEMON_COMMAND_MODEL_URL=http://127.0.0.1:8787/predict
DAEMON_COMMAND_MODEL_MIN_CONFIDENCE=0.70
```

`SHADOW=true` evaluates model and logs it, but keeps regex decisions.
