# fine_tuning_model

## Purpose

Fine-tune a small open LLM (Llama-3 8B) for CloudOps function calling: convert natural language operations instructions into structured JSON payloads suitable for AWS API calls.

## Status

Scaffold complete — `cloudops_fc` package exists under src-layout, uv-managed Python 3.12, schema-validation test suite, quality tooling (ruff, mypy) configured, git initialized. Repository uses Spec-Driven Development (SDD) with strict TDD. Scaffolded on 2026-07-24.

**Tools schemas complete** (2026-07-24): Three production-ready JSON Schema tool definitions (`create_ec2_instance`, `restart_database`, `get_billing_alert`) in Draft 2020-12 with OpenAI function-calling format. Shared 12-region enum. `tool_definitions.json` auto-generated from source schemas. Validation parametrized across 3 schemas with 40 tests (11 billing-specific + existing coverage). `get_billing_alert` added via the tool-billing-alert change.

## Baseline (post-scaffold)

| Area | Technology |
| --- | --- |
| Language | Python 3.12 (uv-managed, `requires-python = ">=3.12,<3.13"`) |
| Package | `cloudops_fc` (src-layout, installable via `uv sync`) |
| Validation | JSON Schema Draft 2020-12 via `jsonschema` library |
| Testing | pytest + pytest-cov (coverage threshold: 80%) |
| Lint/Type | ruff (lint + format), mypy (config in place, execution blocked by AppControl on this machine) |
| Environment | uv 0.11.32 standalone, git 2.54.0 |
| Base model | Llama-3 8B (planned, deferred) |
| Fine-tuning | QLoRA via PEFT + TRL (SFTTrainer — planned, deferred) |
| Quantization | bitsandbytes (4-bit — planned, deferred) |
| Framework | HuggingFace Transformers (planned, deferred) |
| Data | HuggingFace `datasets` (planned, deferred) |

## Architecture Direction

Pipeline stages (to be refined by SDD changes):

1. **Dataset preparation** — NL instruction -> structured JSON (AWS API call) pairs; schema validation.
2. **Training** — QLoRA adapters on Llama-3 8B; configurable hyperparameters; checkpointing.
3. **Evaluation** — JSON validity rate, schema conformance, exact-match / field-level accuracy.
4. **Export & inference** — merged or adapter-based artifact; deterministic structured output.

## Conventions

- All changes flow through the SDD pipeline (`openspec/changes/`); see `openspec/config.yaml` for phase rules.
- Function-calling outputs MUST be validated against explicit JSON schemas.
- Training-related proposals MUST state GPU/VRAM requirements and a fallback strategy.
- Technical artifacts (specs, design, tasks, code, comments) are written in English.

## Persistence Mode

`hybrid` — SDD artifacts are stored both as OpenSpec files under `openspec/` and as Engram observations under project `fine_tuning_model`.
