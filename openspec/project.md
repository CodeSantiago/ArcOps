# fine_tuning_model

## Purpose

Fine-tune a small open LLM (Llama-3 8B) for CloudOps function calling: convert natural language operations instructions into structured JSON payloads suitable for AWS API calls.

## Status

Greenfield — no source code yet. Repository initialized for Spec-Driven Development (SDD) on 2026-07-24.

## Planned Stack

| Area | Technology |
| --- | --- |
| Language | Python 3.14.6 (detected) |
| Base model | Llama-3 8B |
| Fine-tuning | QLoRA via PEFT + TRL (SFTTrainer) |
| Quantization | bitsandbytes (4-bit) |
| Framework | HuggingFace Transformers |
| Data | HuggingFace `datasets` |
| Testing | pytest + pytest-cov (planned, not yet installed) |

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
