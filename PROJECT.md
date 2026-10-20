# ArcOps — Project Brief

ArcOps converts natural-language CloudOps instructions into structured JSON tool calls for AWS. It is a QLoRA fine-tune of Qwen2.5-7B-Instruct with a canonical safety layer, local inference, and LocalStack-first execution.

## Problem

Cloud engineers spend time translating routine requests into CLI commands and API payloads. A general-purpose LLM returns prose that still needs parsing. ArcOps returns only the tool call, validated against a schema before anything executes.

## Architecture

```text
CLI / TUI / API / MCP / exec
            │
            ▼
   cloudops_fc.core
   ├── infer()        → local 4-bit model + LoRA adapter
   ├── safety.check() → canonical validation, cost, policies
   └── execute()      → AWS CLI → LocalStack (default) or real AWS (opt-in)
```

### Components

- **Base model**: `Qwen/Qwen2.5-7B-Instruct` (Apache 2.0)
- **Fine-tuning**: QLoRA (4-bit) via PEFT + TRL SFTTrainer
- **Labels**: masked to the assistant/tool-call response (`-100` elsewhere)
- **Adapter**: `CodeSantiago/arcops` (public, 7B only)
- **Safety**: one module (`cloudops_fc.safety`) shared by every interface
- **Execution**: LocalStack by default; real AWS requires `ARC_OPS_REAL=1` and confirmation

### Supported tools

| Tool | AWS API | Required parameters |
|---|---|---|
| `create_ec2_instance` | EC2 RunInstances | `region`, `instance_type` |
| `restart_database` | RDS RebootDBInstance | `db_instance_identifier`, `region` |
| `get_billing_alert` | Cost Explorer GetCostAndUsage | none |

## Dataset integrity

The generator is deterministic (`SEED=42`):

1. Produces **10,854 raw examples**.
2. Deduplicates by canonical `(prompt, tool name, parsed arguments)` → **3,555 unique**.
3. Splits the unique set 80/10/10 with `seed=42` → train 2,844 / val 355 / test 356.
4. Reports dataset size, unique rows, duplicates, seed, overlap, and leakage in every train/eval run.

Deduplication happens before splitting, so identical rows cannot land on both sides. The test partition is produced by the same code path (`pipeline_utils.build_splits`) in training and evaluation.

`data/challenge_set.jsonl` holds 64 manually authored prompts that are not derived from generator templates. It has zero overlap with the training prompts and covers cities, ambiguity, noise, Spanglish, unknown instance types, and read-only billing.

## Evaluation

`eval.py` supports four modes:

- `standard`: in-distribution, deduplicated 80/10/10 split.
- `template`: complete template families held out for test.
- `unseen`: configured region/instance_type/db/port values appear only in test.
- `challenge`: the 64 manual prompts (hardest generalization test).

A consistency gate compares the evaluation split mode and effective seed against the checkpoint's `dataset_metadata.json`. Mismatches are refused.

**Results policy**: no checkpoint is shipped. Historical "100%" numbers came from a split with duplicate leakage and are not trustworthy. Re-run `eval.py` against your adapter under the corrected protocol.

## Operational safety

- Unknown tools, unknown parameters, and missing required fields are blocked.
- `restart_database` is flagged disruptive and requires approval.
- Destructive actions are blocked in the `production` environment.
- MCP execution is LocalStack-only and refuses actions that need interactive approval.
- Real AWS is never a default.

## Status

Implemented: CLI, Textual TUI, FastAPI API, MCP server, LocalStack executor, safety layer, dataset generator, four evaluation modes, CI (lint, mypy, tests, wheel smoke test).

Not implemented: Spanish/multi-turn datasets, additional AWS services (S3, Lambda, IAM), GGUF CPU inference, public 1.5B adapter.

## Commands

See [README.md](README.md) for installation, training, evaluation, API, and MCP instructions.

## License

Apache 2.0
