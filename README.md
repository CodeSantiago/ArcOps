# ArcOps

**Natural language → AWS JSON tool calls. Local inference, validated execution.**

ArcOps fine-tunes Qwen2.5-7B-Instruct with QLoRA to turn CloudOps instructions into structured JSON tool calls. A canonical safety layer validates every call, estimates cost, and gates disruptive actions. Execution targets LocalStack by default; real AWS requires an explicit opt-in.

```text
User: "Create a t3.micro server in us-east-1 with port 80 open"
  ↓  ArcOps fine-tuned model (local, greedy decoding)
Tool call: {"name": "create_ec2_instance", "arguments": {
             "instance_type": "t3.micro", "region": "us-east-1",
             "security_group_rules": [{"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"}]}}
  ↓  Safety layer (schema validation, cost estimate, policy check)
  ↓  LocalStack (AWS simulator) — real AWS only with explicit opt-in
Result: EC2 instance created with the requested inbound rule (~$8/mo)
```

## Status (v1)

| Metric | Value |
|--------|-------|
| Model | Qwen2.5-7B-Instruct + QLoRA adapter `CodeSantiago/arcops` (4-bit, local) |
| Tools | 3: EC2, RDS, Billing |
| Dataset | 10,854 raw → 3,555 unique; 64 challenge prompts; 0 schema-invalid rows |
| Tool mix | EC2 6,362 / RDS 2,472 / Billing 2,020 |
| Tests | 207 passed, 1 skipped |
| Coverage | 34% overall (≈60% engine, TUI 0%); schemas 100%, models 98%, safety 62%, core 52%, CLI 48% |
| Lint / types | `ruff` clean; `mypy --strict` clean across 7 source files |
| Quick eval | 5 built-in cases, public adapter: tool 5/5, field 6/11 (54.5%), exact 2/5 (40%) |
| End-to-end | EC2 create against LocalStack 3.0 on Windows + RTX 5070 |

The quick eval is a five-case smoke test on in-distribution prompts, not a benchmark. Model accuracy is only meaningful with the correct split mode; see [Evaluation](#evaluation).

## Quick path

Requirements: Python 3.12 or 3.13, an NVIDIA GPU with ~12 GB VRAM for the default 7B model, Docker for LocalStack, and the AWS CLI for execution.

1. **Install the CLI and training extras**

   ```bash
   git clone https://github.com/CodeSantiago/ArcOps.git
   cd ArcOps
   pip install -e ".[train,tui]"
   ```

   The package is not published on PyPI yet. The base install (no PyTorch) still provides `arcops --help` and `arcops tools`.

   On Windows, the default `torch` wheel is CPU-only. Replace it with the CUDA 13 build before running inference:

   ```powershell
   uv pip install --reinstall torch --index-url https://download.pytorch.org/whl/cu130
   ```

   CUDA 12.8+ is required for RTX 50-series cards (`sm_120`); the CUDA 13 wheel includes that support. Training is tested on Linux/WSL2.

2. **Run a prompt**

   ```bash
   arcops "Create a t3.micro server in us-east-1 with port 80"
   ```

   The first call downloads the base model and adapter from HuggingFace and loads them in 4-bit.

3. **Open the dashboard**

   ```bash
   arcops tui
   ```

   The TUI and the CLI share one engine (`cloudops_fc.core`): same inference, same safety checks, same AWS execution.

## Interfaces

| Interface | Command | Notes |
|-----------|---------|-------|
| CLI | `arcops "prompt"` | Tool call plus safety feedback |
| CLI (JSON) | `arcops --json "prompt"` | Machine-readable output |
| Quick eval | `arcops --eval` | 5 built-in cases; requires the model |
| TUI | `arcops tui` | Textual dashboard over the same engine |
| API | `pip install -e ".[api]"` then `python -m app.api` | Localhost-bound FastAPI |
| MCP | `uv run --extra train python scripts/mcp_server.py` | `cloudops_plan` and `cloudops_execute` |
| Exec demo | `python -m app.exec "prompt"` | Plan by default; `--live` for LocalStack |

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ARC_OPS_MODEL` | `7b` | `7b` or `1.5b` |
| `ARC_OPS_ADAPTER` | `CodeSantiago/arcops` | HuggingFace adapter repo ID; required for `1.5b` |
| `ARC_OPS_OFFLOAD_DIR` | system temp | CPU offload folder for the adapter |
| `ARC_OPS_REAL` | unset | Set to `1` to allow real-AWS execution |
| `ARC_OPS_API_KEY` | unset | Require `X-API-Key` on the REST API |

## Model selection

| Key | Base model | Default adapter |
|-----|-----------|-----------------|
| `7b` (default) | `Qwen/Qwen2.5-7B-Instruct` | `CodeSantiago/arcops` (public) |
| `1.5b` | `Qwen/Qwen2.5-1.5B-Instruct` | none |

There is no public 1.5B adapter. Selecting `1.5b` without `ARC_OPS_ADAPTER` fails with a clear error instead of inventing a repo ID.

```bash
export ARC_OPS_MODEL=1.5b
export ARC_OPS_ADAPTER=your-org/your-1.5b-adapter
arcops "Create a t3.micro server"
```

## Safety and execution

One canonical module (`cloudops_fc.safety`) is used by the CLI, TUI, API, MCP server, and `app/exec`:

| Check | Behavior |
|-------|----------|
| Schema validation | Enforces the packaged JSON Schema (types, patterns, enums, extra keys) |
| Required fields | Blocks missing mandatory parameters (no silent defaults) |
| Unknown tools | Blocks tools outside the registry |
| Supported EC2 types | Blocks instance types outside the priced/safety set |
| Cost estimation | Reports monthly EC2 cost before creation |
| Approval | Disruptive actions (DB restart) require confirmation |
| Policy | Destructive actions are blocked in `production` |

Execution details:

- EC2 calls apply `security_group_rules` by creating a security group and authorizing each rule before `run-instances`.
- `tags`, `ami_id`, `key_name`, `subnet_id`, `associate_public_ip`, and `min_count` are passed through; `min_count` maps to the AWS CLI `--count` (the CLI exposes one count, not a range).
- LocalStack uses `ARC_OPS_DEFAULT_AMI` (default `ami-12345678`) when the model omits `ami_id`; real AWS requires an explicit `ami_id`.
- RDS reboots pass `--force-failover` when requested.
- `get_billing_alert` is read-only; Cost Explorer is not available in LocalStack.
- LocalStack community 3.0 implements EC2; `restart_database` needs LocalStack Pro or real AWS.
- Real AWS requires `ARC_OPS_REAL=1` plus an interactive confirmation. MCP execution is LocalStack-only and refuses disruptive actions because it has no approval channel.

## Supported tools

| Tool | AWS API | Parameters |
|------|---------|------------|
| `create_ec2_instance` | EC2 RunInstances | `region`, `instance_type` (required); `ami_id`, `security_group_rules`, `tags`, `key_name`, `subnet_id`, `associate_public_ip`, `min_count`, `max_count` |
| `restart_database` | RDS RebootDBInstance | `db_instance_identifier`, `region` (required); `force_failover` |
| `get_billing_alert` | Cost Explorer GetCostAndUsage | `time_period_start`, `time_period_end`, `granularity`, `metrics`, `group_by_service` |

The AWS CLI exposes a single instance count; `min_count` is used as `--count`. `max_count` is validated but not expressible as a range through this CLI call.

## Dataset

The generator is deterministic (`SEED=42`):

- **10,854 raw synthetic rows** → **3,555 unique examples** after canonical `(prompt, tool, arguments)` deduplication.
- Deduplication runs **before** the seeded 80/10/10 split: train 2,844 / val 355 / test 356. Train/test overlap is reported and is zero.
- Every generator prompt maps to one of **15 template families**, which enables the strict family holdout.
- `data/challenge_set.jsonl` contains **64 manually authored, non-template prompts**: cities, ambiguity, noise, Spanglish, unknown instance types, and read-only billing. It has zero overlap with the training prompts.
- **Tool mix:** EC2 6,362 / RDS 2,472 / Billing 2,020.
- **Schema audit:** all 10,854 rows validate against the packaged JSON Schemas (0 invalid rows).

The generated training set is intentionally gitignored; the 64-prompt challenge set is tracked. Regenerate the training data locally:

```bash
python scripts/generate_dataset_v3.py
```

## Training

Training requires an NVIDIA GPU (Linux or WSL2 recommended):

```bash
uv sync --extra train

# Quick iteration: rank 16, 2 epochs
python scripts/training/train.py --config scripts/training/quick_config.yaml

# Full run: rank 32, 6 epochs
python scripts/training/train.py --config scripts/training/default_config.yaml

# Full pipeline on WSL2: sync → smoke test → train → eval
bash scripts/training/run.sh
```

Training data is split exactly like evaluation (`scripts/training/pipeline_utils.build_splits`), and labels are masked to the assistant response only.

### Generalization splits

```bash
# Train without two complete template families
python scripts/training/train.py --config scripts/training/default_config.yaml \
  --split-mode template --test-families ec2_ports,rds_failover

# Train without specific region and port values
python scripts/training/train.py --config scripts/training/default_config.yaml \
  --split-mode unseen --unseen region=ap-northeast-1,ca-central-1 --unseen port=6379
```

## Evaluation

`scripts/training/eval.py` supports four modes. Each mode measures something different; always report the mode next to the score.

| Mode | Command | What it measures |
|------|---------|------------------|
| `standard` | `eval.py --checkpoint checkpoints/final` | In-distribution: deduplicated 80/10/10 split |
| `template` | `... --eval-mode template --test-families ec2_ports,rds_failover` | Unseen phrasing: complete families held out |
| `unseen` | `... --eval-mode unseen --unseen region=ap-northeast-1,ca-central-1 --unseen port=6379` | Unseen values: holdout values appear only in test |
| `challenge` | `... --eval-mode challenge` | Unseen language: the 64 manual prompts |

The consistency gate refuses an evaluation whose split mode or effective seed differs from the checkpoint's `dataset_metadata.json`. Reports are saved as `eval_report_<mode>.json` next to the adapter.

**Quick eval (public adapter).** `arcops --eval` runs five built-in cases: tool accuracy 5/5, field accuracy 6/11 (54.5%), exact match 2/5 (40%). This is a smoke test, not a benchmark; use `eval.py` with the correct split mode for real numbers.

**Results policy.** No checkpoint is shipped in this repository, and historical "100%" numbers were measured on a split that leaked duplicates. The current pipeline deduplicates before splitting and enforces the consistency gate. Run `eval.py` against your own adapter; do not treat old numbers in git history as verified.

## API

```bash
pip install -e ".[api]"
python -m app.api                 # binds 127.0.0.1:8080
uvicorn app.api:app --host 127.0.0.1 --port 8080
```

- `max_tokens` is clamped to 1..1024.
- Set `ARC_OPS_API_KEY` to require `X-API-Key`.
- Schema violations return HTTP 400.

## Docker

```bash
docker build -t arcops .
docker run --gpus all -p 8080:8080 arcops
curl -s localhost:8080/predict \
  -d '{"prompt":"Create a t3.micro server in us-east-1"}' \
  -H "Content-Type: application/json"
```

The image pins PyTorch 2.14.1 + CUDA 13.0 (RTX 50-series / `sm_120`). It is not built in CI; build it on a machine with Docker and enough disk.

The container binds `0.0.0.0` because Docker port publishing requires it. Do not expose it publicly without `ARC_OPS_API_KEY`.

## MCP

Add to your MCP client configuration:

```json
{
  "mcp": {
    "arcops": {
      "command": ["uv", "run", "--extra", "train", "python", "scripts/mcp_server.py"],
      "type": "local"
    }
  }
}
```

The server exposes `cloudops_plan` (inference only) and `cloudops_execute` (inference plus LocalStack execution).

## Project structure

```text
ArcOps/
├── src/cloudops_fc/
│   ├── core.py                 # Shared engine: inference + safety + AWS execution
│   ├── cli.py                  # `arcops` console entry point
│   ├── tui.py                  # Textual dashboard (installed with the tui extra)
│   ├── models.py               # ARC_OPS_MODEL resolution (7b / 1.5b)
│   ├── safety.py               # Canonical safety layer
│   ├── py.typed
│   └── schemas/                # Packaged JSON Schemas
├── app/                        # Repo-only tools
│   ├── api.py                  # FastAPI server
│   ├── exec.py                 # Plan / LocalStack executor
│   ├── index.html              # Optional web UI served at /
│   ├── tui.py                  # Compatibility shim → cloudops_fc.tui
│   └── safety.py               # Compatibility shim → cloudops_fc.safety
├── scripts/
│   ├── generate_dataset_v3.py  # Deterministic dataset generator
│   ├── mcp_server.py           # MCP server
│   └── training/               # train.py, eval.py, splits, configs, run.sh
├── data/
│   ├── challenge_set.jsonl     # 64 manual prompts (tracked)
│   └── training_dataset.jsonl  # generated locally (gitignored)
├── tests/                      # Non-GPU pytest suite
├── LICENSE                     # Apache 2.0
└── .github/workflows/ci.yml    # Lint + mypy + tests + wheel smoke test
```

## Development

```bash
pip install -e ".[dev]"
pytest -q
pytest -q --cov=cloudops_fc --cov-report=term
ruff check src/ cloudops.py app/ tests/ scripts/
mypy src/cloudops_fc
```

CI runs on Python 3.12/3.13 without the ML stack: lint, mypy, module imports, `app.exec --help`, packaged-schema checks, the full test suite, and a wheel smoke test.

## Known limitations

- The dataset is English-only synthetic data; Spanish and multi-turn conversations are not covered.
- No checkpoint is shipped; the public adapter is 7B only.
- `get_billing_alert` is a read-only planning tool and does not execute Cost Explorer in LocalStack.
- `restart_database` needs LocalStack Pro or real AWS; LocalStack community 3.0 does not implement RDS.
- The TUI is manually/integration tested; it has no automated pytest coverage (the engine is covered).
- The 10,854-row training dataset is generated locally and gitignored; the deterministic generator and the 64-prompt challenge set are tracked.
- Windows GPU inference requires the CUDA 13 build of torch; the default PyPI wheel is CPU-only.
- The Docker image is not built in CI; it pins PyTorch 2.14.1 + CUDA 13.0.
- MCP execution never targets real AWS and refuses disruptive actions.
- The API has no rate limiting; keep it on localhost or set `ARC_OPS_API_KEY`.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

[Report a bug](https://github.com/CodeSantiago/ArcOps/issues) · [Contribute](https://github.com/CodeSantiago/ArcOps/pulls) · [HuggingFace adapter](https://huggingface.co/CodeSantiago/arcops)
