# Proposal: Training Pipeline — QLoRA Fine-Tuning on RTX 5070

## Intent

Fine-tune Llama-3 8B with QLoRA to convert Spanish NL instructions into structured tool calls for 3 CloudOps functions (create_ec2_instance, restart_database, get_billing_alert). The change delivers a reproducible training pipeline with eval metrics, checkpointing, and a deployable LoRA adapter artifact.

## Scope

### In Scope
- Training pipeline: `scripts/train.py` + `scripts/train_config.py` + ML dependency group in pyproject.toml
- WSL2 runtime setup: uv, CUDA toolkit, project sync
- bitsandbytes smoke test (Blackwell sm_120 compatibility gate)
- QLoRA training: 4-bit NF4, r=16, bf16, batch=1, 3 epochs
- Eval: exact-match, tool-name accuracy, schema conformance, field accuracy
- Export: LoRA adapter only (~34 MB) to WSL2 native fs

### Out of Scope
- Merged-16bit or GGUF export (deferred)
- HuggingFace Hub upload (deferred)
- Non-Blackwell GPU support (RTX 5070 only)
- Non-Spanish dataset or multi-language support
- Dataset generation or augmentation
- Inference server or API wrapper

## Capabilities

### New Capabilities
- `training-pipeline`: end-to-end training workflow (env setup, dataset loading, QLoRA fine-tuning, evaluation, checkpointing, adapter export)

### Modified Capabilities
- None — training consumes existing tool schemas without changing them

## Approach

Four phases, each gating the next:

1. **Smoke test (1 task)**: Install bitsandbytes in WSL2, confirm `bnb.nn.Linear4bit` loads a 4-bit model. If Blackwell wheels missing, compile from source with `CUDA_ARCH_LIST=sm_120`. Gate: bitsandbytes operational.
2. **Pipeline code (2 tasks)**: Write `train_config.py` (hyperparameter config) and `train.py` (dataset load → tokenize → SFTTrainer → checkpoint). Use DataCollatorForCompletionOnlyLM with assistant response template.
3. **Train run (1 task)**: Execute 3-epoch QLoRA run on WSL2. Monitor VRAM with nvidia-smi. Evaluate on 20% holdout. Save adapter to `./checkpoints/final/`.
4. **Eval & export (1 task)**: Compute 4 metrics, generate report, export LoRA-only artifact.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `scripts/train.py` | New | Main training entrypoint |
| `scripts/train_config.py` | New | Hyperparameter config (Pydantic/YAML) |
| `pyproject.toml` | Modified | ML dependencies (train optional-deps group) |
| WSL2 `~/fine_tuning_model/` | New | Project copy for training runtime |
| `openspec/changes/training-pipeline/` | New | SDD artifacts |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| bitsandbytes lacks sm_120 wheels | High | Phase-1 smoke test gates all training; fallback: compile from source |
| OOM at 12GB VRAM | Medium | batch=1, grad checkpointing, bf16; fallback: reduce seq to 384 or r to 8 |
| OneDrive sync corruption | Low | Run on WSL2 native fs; sync artifacts only on successful completion |
| Spanish dataset on English-pretrained model | Low | 3 epochs + 2e-4 LR; eval on holdout to detect overfitting early |
| PyTorch + CUDA 12.8 version mismatch | Medium | Use `--pre torch --index-url https://download.pytorch.org/whl/nightly/cu128` if needed |

## Rollback Plan

- **Dependencies**: `git revert pyproject.toml` to remove ML deps group
- **Scripts**: `git rm scripts/train.py scripts/train_config.py`
- **WSL2 runtime**: `rm -rf ~/fine_tuning_model/` — training copy is disposable
- **Checkpoints**: Wipe `./checkpoints/` — adapter is not referenced by any production code

## Dependencies

- HuggingFace token for `meta-llama/Meta-Llama-3-8B` (gated model, user must accept license)
- bitsandbytes ≥0.45 with sm_120 support (validated in phase 1)
- WSL2 with CUDA toolkit 12.8, uv, Python 3.12

## Success Criteria

- [ ] bitsandbytes loads and 4-bit model fits in VRAM (smoke test passes)
- [ ] Training completes 3 epochs without OOM
- [ ] Eval: tool-name accuracy ≥95%, exact-match ≥80%
- [ ] LoRA adapter exported to `./checkpoints/final/` (~34 MB)
- [ ] All eval metrics logged to a report file
