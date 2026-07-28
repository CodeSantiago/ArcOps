# Tasks: Training Pipeline — QLoRA Fine-Tuning on RTX 5070

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~490 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1: Setup + Smoke → PR 2: Pipeline |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Environment + Smoke Test | PR 1 | pyproject.toml, smoke_test.py, default_config.yaml. Base = main. Code + deps reviewed together. |
| 2 | Pipeline Code + Automation | PR 2 | train_config.py, train.py, eval.py, run.sh. Base = main (code independent; execution gated by PR 1 smoke test). |

## Phase 1: Smoke Test — 🔴 CRITICAL GATE

- [x] 1.1 Create `scripts/training/smoke_test.py`: CUDA check, bitsandbytes import, 4-bit model load, forward pass, VRAM report
- [x] 1.2 Modify `pyproject.toml`: add `[project.optional-dependencies] train` group (torch>=2.6, transformers>=4.47, peft>=0.14, trl>=0.15, bitsandbytes>=0.45, datasets>=3.2, accelerate>=1.2, huggingface_hub>=0.27)
- [ ] 1.3 If no sm_120 wheel: compile bitsandbytes from source with `CUDA_ARCH_LIST=sm_120`
- [x] 1.4 Create `scripts/training/default_config.yaml` with hyperparameters from design
- [ ] 1.5 Run on WSL2: `uv sync --group train`, execute smoke_test.py, confirm exit 0

## Phase 2: Pipeline Code

- [x] 2.1 Create `scripts/training/train_config.py`: Pydantic TrainingConfig (ModelConfig, LoraConfig, TrainingArgs, DataConfig) + YAML load/save round-trip
- [x] 2.2 Create `scripts/training/train.py`: dataset load → custom ChatML formatter (tool_calls→JSON text) → tokenize → DataCollatorForCompletionOnlyLM → SFTTrainer → checkpoint
- [x] 2.3 Create `scripts/training/eval.py`: exact-match, tool-name accuracy, field accuracy; write `checkpoints/eval_report.json`

## Phase 3: Train Run (WSL2)

- [ ] 3.1 Execute 3-epoch QLoRA run on WSL2; monitor VRAM; verify checkpoints; confirm no OOM
- [ ] 3.2 If OOM: reduce max_seq_length to 384 or lora r to 8, retry

## Phase 4: Eval & Export

- [ ] 4.1 Run eval.py on holdout; verify tool-name accuracy ≥95%, exact-match ≥80%
- [x] 4.2 Create `scripts/training/run.sh`: rsync → uv sync → smoke → train → eval — single reproducible entrypoint
- [ ] 4.3 Export LoRA adapter to `./checkpoints/final/`; verify size ~34 MB
