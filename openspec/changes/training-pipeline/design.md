# Design: Training Pipeline — QLoRA Fine-Tuning on RTX 5070

## Technical Approach

SFTTrainer-based QLoRA pipeline with 4 phases gated by a bitsandbytes Blackwell smoke test. Dataset stays in OpenAI tool_calls format (custom formatting — no HF tool_use conversion). Run entirely in WSL2 native fs, LoRA-only export. Config via Pydantic + YAML.

## Architecture Decisions

### Decision: Custom dataset formatting over HF native tool_use

| Option | Tradeoff |
|--------|----------|
| A. HF native format | Convert dataset; future-proof, SFTTrainer tool handling — Medium effort |
| B. **Custom formatting** | Keep dataset as-is; simpler, full control — Low effort |

**Choice**: B — Custom formatting for v1. Format each example as `system + user NL → serialized JSON tool_call` as assistant text. Upgrade to native format post-v1 if needed.

### Decision: SFTTrainer + DataCollatorForCompletionOnlyLM

| Option | Tradeoff |
|--------|----------|
| A. **SFTTrainer + DataCollator** | Standard TRL pattern, labels auto-masked |
| B. Manual Trainer loop | Full control but boilerplate-heavy |
| C. axolotl config | Declarative but extra dependency |

**Choice**: A. Use `response_template="<|start_header_id|>assistant<|end_header_id|>"` for label masking.

### Decision: LoRA adapter-only export

| Option | Size | Tradeoff |
|--------|------|----------|
| **LoRA adapter** | ~34 MB | Needs base model at inference |
| Merged 4-bit | ~4.5 GB | Self-contained but large |
| GGUF | ~4.7 GB | CPU compatible, extra step |

**Choice**: LoRA adapter only. Merged/GGUF deferred.

### Decision: bitsandbytes source compilation fallback

**Choice**: Phase-1 smoke test validates bnb + sm_120. If no wheel, compile from source with `CUDA_ARCH_LIST=sm_120`. This gates all subsequent phases.

### Decision: Pydantic config over raw dataclass

**Choice**: `train_config.py` uses Pydantic `BaseModel` for hyperparameter config with YAML serialization. Validates types at load time, avoids magic numbers.

## Data Flow

```
training_dataset.jsonl
       │
       ▼
datasets.load_dataset("json")
       │
       ▼
80/20 stratified split (by tool name)
       │
       ▼
Custom formatter: ChatML → tokenizer.apply_chat_template()
  - system: Eres un asistente de infraestructura cloud...
  - user: NL instruction
  - assistant: serialized JSON tool_call
       │
       ▼
Tokenize (max_seq_length=512, truncate)
       │
       ▼
DataCollatorForCompletionOnlyLM (mask user/system labels)
       │
       ▼
SFTTrainer (QLoRA)
  │           │
  ▼           ▼
checkpoints/  eval metrics
  │
  ▼
final/adapter (~34 MB)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `scripts/training/train.py` | Create | Main entrypoint: load config → dataset → SFTTrainer → train → save adapter |
| `scripts/training/train_config.py` | Create | Pydantic TrainingConfig + YAML save/load + default config |
| `scripts/training/smoke_test.py` | Create | Validate bnb loads 4-bit model, VRAM fits, CUDA available |
| `scripts/training/eval.py` | Create | Compute 4 metrics on holdout set, produce report |
| `scripts/training/run.sh` | Create | WSL2 launcher: rsync project, uv sync, run smoke/train/eval |
| `scripts/training/default_config.yaml` | Create | Default hyperparameter YAML |
| `pyproject.toml` | Modify | Add `[project.optional-dependencies] train = [...]` group |

### Training Config (default_config.yaml)

```yaml
model:
  name: meta-llama/Meta-Llama-3-8B
  load_in_4bit: true
  bnb_4bit_quant_type: nf4
  bnb_4bit_compute_dtype: bf16
  bnb_4bit_use_double_quant: true

lora:
  r: 16
  lora_alpha: 32
  target_modules:
    - q_proj
    - v_proj
    - k_proj
    - o_proj
    - gate_proj
    - up_proj
    - down_proj
  lora_dropout: 0.1

training:
  per_device_train_batch_size: 1
  per_device_eval_batch_size: 1
  gradient_accumulation_steps: 8
  gradient_checkpointing: true
  learning_rate: 2.0e-4
  num_train_epochs: 3
  warmup_ratio: 0.1
  logging_steps: 10
  save_steps: 200
  eval_steps: 200
  save_total_limit: 3
  optim: adamw_8bit
  bf16: true
  max_grad_norm: 0.3
  lr_scheduler_type: cosine
  max_seq_length: 512
  output_dir: ./checkpoints
  report_to: none

data:
  train_file: ../../data/training_dataset.jsonl
  val_split: 0.2
  seed: 42
```

## Interfaces

### TrainingConfig (Pydantic)

```python
class TrainingConfig(BaseModel):
    model: ModelConfig
    lora: LoraConfig
    training: TrainingArgs
    data: DataConfig

    @classmethod
    def from_yaml(cls, path: Path) -> "TrainingConfig": ...
    def to_yaml(self, path: Path) -> None: ...

class ModelConfig(BaseModel):
    name: str
    load_in_4bit: bool = True
    bnb_4bit_quant_type: Literal["nf4", "fp4"] = "nf4"
    bnb_4bit_compute_dtype: str = "bf16"
    bnb_4bit_use_double_quant: bool = True

class LoraConfig(BaseModel):
    r: int = 16
    lora_alpha: int = 32
    target_modules: list[str]
    lora_dropout: float = 0.1

class TrainingArgs(BaseModel):
    per_device_train_batch_size: int = 1
    gradient_accumulation_steps: int = 8
    gradient_checkpointing: bool = True
    learning_rate: float = 2e-4
    num_train_epochs: int = 3
    bf16: bool = True
    max_seq_length: int = 512

class DataConfig(BaseModel):
    train_file: str
    val_split: float = 0.2
    seed: int = 42
```

## Smoke Test Protocol

```
smoke_test.py:
  1. import torch; assert torch.cuda.is_available()
  2. import bitsandbytes as bnb
  3. Load 4-bit model via AutoModelForCausalLM.from_pretrained(..., load_in_4bit=True)
  4. Forward pass on dummy input (1 token)
  5. Report: VRAM used, CUDA arch, bnb version, success/fail
```

Gate: smoke_test.py must exit 0 before any training step runs.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | TrainingConfig validation | Pydantic round-trip, YAML load/save |
| Unit | Dataset formatting function | Given raw ChatML → verify tokenized assistant labels masked |
| Unit | Eval metric computation | Known inputs → assert exact-match, tool_accuracy |
| Integration | Smoke test on WSL2 | Real bnb import + 4-bit load (manual trigger) |
| E2E | Full train run | WSL2: 1 epoch on 10 examples, assert checkpoint created (manual) |

## Evaluation Metrics

| Metric | Definition |
|--------|------------|
| Exact match | Generated JSON == expected (char-for-char) |
| Tool name accuracy | correct tool selected |
| Schema conformance | JSON valid against tool_definitions.json |
| Field accuracy | Correct parameter values |

Eval runs at `eval_steps=200` on 20% holdout (~520 examples). Final report written to `checkpoints/eval_report.json`.

## Migration / Rollback

No migration required. Training pipeline is additive — existing code unchanged. Rollback: `git revert pyproject.toml && git rm -r scripts/training/ && rm -rf ~/fine_tuning_model/checkpoints/`.

## Open Questions

- [ ] PyTorch CUDA 12.8 compatibility — confirm `--pre torch --index-url https://download.pytorch.org/whl/nightly/cu128` is needed or stable torch 2.6+ suffices
- [ ] bitsandbytes pre-built wheels for sm_120 — will be resolved by smoke test
