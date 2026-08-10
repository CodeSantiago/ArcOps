# ArcOps

**Natural language → AWS JSON tool calls. 100% local. No data leaves your machine.**

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python">
  <img src="https://img.shields.io/badge/model-7B%20QLoRA-orange" alt="Model">
</p>

ArcOps is a fine-tuned language model (Qwen2.5-7B-Instruct + QLoRA) that converts CloudOps instructions into structured JSON tool calls ready for AWS API execution. The model, inference, and safety checks all run on your hardware — no OpenAI, no API costs, no third-party data flow.

```
User: "Create a t3.micro server in us-east-1 with port 80 open"
  ↓  ArcOps fine-tuned model (local, greedy decoding)
Tool call: {"name": "create_ec2_instance", "arguments": {
             "instance_type": "t3.micro", "region": "us-east-1",
             "security_group_rules": [{"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"}]}}
  ↓  Safety layer (schema validation, cost estimate, policy check)
  ↓  LocalStack (AWS simulator) — real AWS only with explicit opt-in
Result: EC2 instance created (~$8/mo)
```

---

## Quick Start

### Prerequisites

- NVIDIA GPU with ~12 GB VRAM (the default 7B model loads in 4-bit; `--light` uses the 1.5B model for lighter hardware)
- Python 3.12+
- Docker (for LocalStack simulation)
- AWS CLI (execution runs through the AWS CLI)

### Install

The base package is lightweight (CLI + safety, no PyTorch). Install the extras for the full experience:

```bash
pip install 'cloudops-fc[train,tui]'     # inference + terminal dashboard
```

Extras: `train` (torch/transformers/peft ML stack), `tui` (Textual dashboard), `dev` (pytest, ruff, mypy).

> **uv note:** use `uv sync --extra train --extra dev --extra tui` — bare `--extra` prunes the other extras.

### Run

```bash
# CLI — natural language to a tool call
arcops "Create a t3.micro server in us-east-1 with port 80"

# TUI — dashboard over the same engine (see Interfaces)
arcops tui
```

First inference downloads the base model + adapter from HuggingFace and loads it in 4-bit (~30 s on the first call; subsequent calls are fast). Metadata commands (`arcops --help`, `arcops tools`) work without the ML stack.

---

## Interfaces

The CLI and the TUI are **two faces over one engine** (`cloudops_fc.core`) — same inference, same safety checks, same AWS execution. There is no model-server socket; the TUI loads the model in-process.

### CLI

| Command | What it does |
|---------|--------------|
| `arcops "prompt"` | Infer a tool call and show it with safety feedback |
| `arcops --json "prompt"` | Raw JSON output (for scripts) |
| `arcops --light "prompt"` | Use the 1.5B model (needs `ARC_OPS_ADAPTER`) |
| `arcops --eval` | Quick accuracy check on 5 built-in cases |
| `arcops tools` | List supported tools |
| `arcops tui` | Launch the terminal dashboard |

### TUI

A Textual 1.x dashboard (catppuccin-mocha theme) that lists resources, accepts natural-language prompts, and runs actions against LocalStack. Pure presentation — every AWS call and all inference live in the engine. Press `l` to launch LocalStack.

### Other entry points

- **API** — `app/api.py`, a localhost-bound FastAPI server (`python -m app.api`); optional `X-API-Key` via `ARC_OPS_API_KEY`.
- **MCP server** — `scripts/mcp_server.py`, exposes ArcOps to opencode/Claude/Cursor as a local MCP tool.

### Environment variables (see `.env.example`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `ARC_OPS_MODEL` | `7b` | Model size: `7b` or `1.5b` |
| `ARC_OPS_ADAPTER` | `CodeSantiago/arcops` | HuggingFace adapter repo ID (required for `1.5b`) |
| `ARC_OPS_OFFLOAD_DIR` | system temp | CPU offload folder for the adapter |
| `ARC_OPS_REAL` | unset | Set to `1` to allow real-AWS mode |
| `ARC_OPS_API_KEY` | unset | Optional API key for the REST API |

---

## How It Works

1. **Inference** — `core.infer()` runs the fine-tuned model in-process (greedy decoding; deterministic output) and returns a JSON tool call.
2. **Safety** — `cloudops_fc.safety` validates the call against the tool schemas before anything executes: unknown parameters are blocked, missing required fields are blocked, cost is estimated, disruptive actions require approval.
3. **Execution** — tool calls run through the AWS CLI against **LocalStack by default**. Real AWS is never a default: it requires `ARC_OPS_REAL=1` *and* an interactive confirmation.

## Safety Layer

One canonical module (`cloudops_fc.safety`) is used by every interface. No tool call executes without passing it.

| Check | What it does |
|-------|-------------|
| Schema validation | Rejects invented parameters (e.g. `log_event`) |
| Required fields | Blocks calls missing mandatory params (no silent defaults) |
| Unknown tools | Blocks tools outside the schema |
| Cost estimation | Shows a monthly cost estimate before creating resources |
| Approval | Destructive/disruptive actions (e.g. DB restart, terminate) require explicit confirmation |
| Policy enforcement | Blocks destructive operations in the `production` environment |

```
> Create a t3.micro server in us-east-1

-- Safety Check --
Estimated cost: ~$8/mo (t3.micro x1)

[ok] Created i-12345678
```

---

## Supported Tools

| Tool | AWS API | Parameters |
|------|---------|------------|
| `create_ec2_instance` | EC2 RunInstances | `region`, `instance_type` (required); `security_group_rules`, `tags`, `key_name`, `subnet_id`, `associate_public_ip`, `ami_id`, `min_count`, `max_count` |
| `restart_database` | RDS RebootDBInstance | `db_instance_identifier`, `region` (required); `force_failover` |
| `get_billing_alert` | Cost Explorer GetCostAndUsage | `time_period_start`, `time_period_end`, `granularity`, `metrics`, `group_by_service` |

---

## Model Selection

`ARC_OPS_MODEL` accepts exactly two values, resolved identically across all interfaces:

| Key | Base model | Default adapter |
|-----|-----------|-----------------|
| `7b` (default) | `Qwen/Qwen2.5-7B-Instruct` | `CodeSantiago/arcops` (public) |
| `1.5b` | `Qwen/Qwen2.5-1.5B-Instruct` | **none** |

There is **no public 1.5B adapter**. Selecting `1.5b` without an explicit adapter fails with a clear error — the project never invents a repo ID. To use a 1.5B fine-tune of your own:

```bash
export ARC_OPS_MODEL=1.5b
export ARC_OPS_ADAPTER=your-org/your-1.5b-adapter   # required
arcops "Create a t3.micro server"
```

`arcops --light` is a shorthand for `ARC_OPS_MODEL=1.5b` and is subject to the same adapter requirement.

---

## Training & Evaluation

### Dataset

Generated deterministically (`SEED=42`) by `scripts/generate_dataset_v3.py`:

- **11,510 synthetic rows** across 3 tools and 12 regions, deduplicated by canonical `(prompt, tool name, parsed arguments)` to **3,555 unique examples**.
- The v3 generator includes three "honest fixes": default sizes, city→region mapping, and relative-time billing.
- **No train/test leakage**: duplicates are removed before the seeded split; split metadata reports size, unique rows, duplicates, seed, and train/test overlap.
- `data/challenge_set.jsonl` (tracked) holds **64 manually authored, non-template prompts**: city names, ambiguous requests, noise phrases, Spanglish, unknown instance types, and read-only billing.
- `data/training_dataset.jsonl` is **gitignored** — regenerate it locally with `python scripts/generate_dataset_v3.py`.

### Evaluation protocol

`scripts/training/eval.py` runs one of **four modes** and reports exact-match, tool-name, and field accuracy per run:

| Mode | Command | What it measures |
|------|---------|------------------|
| `standard` (default) | `eval.py --checkpoint checkpoints/final` | In-distribution: deduplicated 80/10/10 seeded split |
| `template` | `... --eval-mode template --test-families ec2_ports,rds_failover` | Unseen phrasing: complete template families held out |
| `unseen` | `... --eval-mode unseen --unseen region=ap-northeast-1,ca-central-1 --unseen port=6379` | Unseen values: holdout values appear only in test |
| `challenge` | `... --eval-mode challenge` | Unseen language: the 64 manual prompts — the hardest test |

Every run is guarded by a **strict consistency gate**: `verify_split_consistency` refuses template/unseen evaluation unless the eval split matches the checkpoint's `checkpoints/dataset_metadata.json` (mode + seed + families/values). Reports are saved as `eval_report_<mode>.json` next to the adapter.

Always report the mode name next to a score — "accuracy" without a mode is meaningless. The modes measure different things and must not be compared as one benchmark.

### Results (final, honest)

| Mode | n | Exact | Field | Tool |
|------|---|-------|-------|------|
| `standard` | 356 | **100%** (356/356) | — | — |
| `unseen` (seed 42) | 352 | **100%** (352/352) | — | — |
| `challenge` | 64 manual prompts | **79.69%** | **92.81%** | **98.44%** |

Earlier published "100%" results were measured on an inflated split (identical examples in train and test). The pipeline now deduplicates before splitting and enforces the consistency gate, so these are the numbers to trust. Template-mode results are re-measured per checkpoint via the command above.

---

## Architecture

```
ArcOps/
├── src/cloudops_fc/            # Installed package (cloudops-fc)
│   ├── core.py                 # Shared engine: inference + AWS execution + safety
│   ├── cli.py                  # `arcops` console command (installed entry point)
│   ├── models.py               # Unified ARC_OPS_MODEL resolution (7b / 1.5b)
│   ├── safety.py               # Canonical safety layer (validation/cost/policies)
│   ├── py.typed                # PEP 561 marker
│   └── schemas/                # Tool definitions (JSON Schema, packaged)
├── app/                        # Repo tools (checkout only)
│   ├── tui.py                  # Textual dashboard — pure presentation
│   ├── api.py                  # FastAPI REST server (localhost default)
│   ├── exec.py                 # NL → AWS CLI builder / LocalStack executor
│   └── safety.py               # Compatibility shim → cloudops_fc.safety
├── scripts/
│   ├── generate_dataset_v3.py  # Deterministic dataset generator
│   ├── mcp_server.py           # MCP protocol server
│   └── training/               # train.py, eval.py, pipeline_utils.py,
│                               # template_families.py, configs, run.sh
├── data/
│   ├── challenge_set.jsonl     # 64 manual generalization prompts (tracked)
│   └── training_dataset.jsonl  # regenerated locally (gitignored)
├── tests/                      # Non-GPU test suite (pytest)
├── .env.example                # Environment configuration template
└── .github/workflows/ci.yml    # CI: lint + non-GPU tests + package smoke test
```

The CLI, TUI, API, MCP server, and `app/exec` all import from the same `cloudops_fc.core` engine — no duplicated logic.

---

## Development

```bash
# Install with test tooling
pip install -e ".[dev]"

# Run the non-GPU test suite
pytest

# Lint
ruff check src/ cloudops.py app/ tests/ scripts/
```

CI (`.github/workflows/ci.yml`) runs on Python 3.12/3.13 without the ML stack: it lints, verifies the packaged JSON schemas, runs the full non-GPU test suite, and smoke-tests the installed `arcops` entry point.

---

## FAQ

**Do I need a GPU?** The default 7B model needs ~12 GB VRAM (4-bit). `arcops --light` targets lighter hardware but requires your own 1.5B adapter.

**Does it touch real AWS?** Not by default. Everything runs against LocalStack unless `ARC_OPS_REAL=1` is set — and real-AWS actions still require interactive confirmation.

**Is output deterministic?** Yes — greedy decoding, same input → same tool call.

**Why is the first call slow?** The model downloads and loads in 4-bit (~30 s once, cached afterward).

**Can I train my own adapter?** Yes — see `scripts/training/`; training requires a NVIDIA GPU (Linux/WSL2 recommended).

**Where is my data?** Nowhere else. Model, inference, and safety all run locally.

---

## License

Apache 2.0

---

[Report a bug](https://github.com/CodeSantiago/ArcOps/issues) · [Contribute](https://github.com/CodeSantiago/ArcOps/pulls) · [HuggingFace model](https://huggingface.co/CodeSantiago/arcops)
