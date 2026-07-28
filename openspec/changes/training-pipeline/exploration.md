# Exploration: Training Pipeline — QLoRA Fine-Tuning on RTX 5070

## Current State

The project has:
- **3 tool schemas** (create_ec2_instance, restart_database, get_billing_alert) in OpenAI function-calling format at `src/cloudops_fc/schemas/tool_definitions.json`
- **2598 training examples** in `data/training_dataset.jsonl` — NL→tool_call pairs in ChatML format (1215 EC2, 827 RDS, 556 billing)
- **Zero ML dependencies** installed (no torch, transformers, peft, trl, bitsandbytes)
- **Python 3.12.3** available in WSL2; **no uv** installed there; project is uv-managed on Windows host
- **RTX 5070 12GB** (Blackwell sm_120, CUDA UMD 13.3, NVIDIA 610.53 driver) — verified working in WSL2
- **~948 GB free disk** on WSL2 root filesystem
- **OneDrive-hosted project** — training should run from WSL2 native fs to avoid sync churn

## Affected Areas

- `scripts/train.py` — **to create**: main training entrypoint
- `scripts/train_config.py` — **to create**: hyperparameter/YAML config
- `data/training_dataset.jsonl` — dataset already exists, no changes needed
- `src/cloudops_fc/schemas/tool_definitions.json` — used for eval (schema conformance)
- `pyproject.toml` — **to update**: add ML dependencies (train optional-deps group)
- `openspec/changes/training-pipeline/` — SDD artifacts
- WSL2 `~/fine_tuning_model/` — project copy for training runtime

## Dataset Analysis

| Metric | Value |
|--------|-------|
| Total examples | 2598 |
| create_ec2_instance | 1215 (46.8%) |
| restart_database | 827 (31.8%) |
| get_billing_alert | 556 (21.4%) |
| Avg chars per example | 538 |
| Max chars | 1281 |
| Min chars | 340 |
| Approx avg tokens (chars/3.5) | ~154 |
| Approx max tokens | ~366 |
| Format | OpenAI ChatML with `tool_calls` |
| System prompt | Spanish: "Eres un asistente de infraestructura cloud..." |

**Key insight**: The dataset is well-distributed across 3 tools with a realistic bias toward EC2 (most common CloudOps action). Max sequence length of 512 tokens safely covers all examples with padding/structural tokens.

## WSL2 Setup

### Current State
| Check | Status |
|-------|--------|
| Python 3.12 | ✅ 3.12.3 pre-installed |
| uv | ❌ Not installed |
| CUDA toolkit | ❌ Not installed (nvidia-smi works via driver) |
| PyTorch with CUDA | ❌ Not installed |
| Project on WSL2 | ❌ Not synced yet |

### Install Plan
1. Install uv in WSL2: `curl -LsSf https://astral.sh/uv/0.6.10/install.sh | sh`
2. Copy project to WSL2 native fs: `rsync -av --exclude .venv --exclude .git /mnt/c/Users/conta/OneDrive/... ~/fine_tuning_model/`
3. Install CUDA 12.8 toolkit in WSL2 (needed for torch compile): `wget ...cuda-keyring.deb && sudo dpkg -i ... && sudo apt-get update && sudo apt-get install cuda-toolkit-12-8`
4. Install ML dependencies via uv

## ML Stack Version Decisions

| Package | Version | Rationale |
|---------|---------|-----------|
| torch | >=2.6.0 | CUDA 12.8+ support, compiled with Blackwell sm_120 support |
| transformers | >=4.47.0 | Llama-3 chat template, tool_usage support |
| peft | >=0.14.0 | QLoRA integration, latest bugfixes |
| trl | >=0.15.0 | SFTTrainer with tool_calls formatting |
| bitsandbytes | >=0.45.0 | 4-bit NF4 quantization, needs Blackwell support |
| datasets | >=3.2.0 | JSONL loading, train/val split |
| accelerate | >=1.2.0 | Device placement, gradient checkpointing |
| huggingface_hub | >=0.27.0 | Model download, LoRA push |

**⚠️ bitsandbytes + Blackwell (sm_120) risk**: As of mid-2026, bitsandbytes may not ship pre-built wheels for sm_120. The RTX 5070 is very new. Fallback options:
- Option A: Compile bitsandbytes from source with `CUDA_ARCH_LIST=sm_120`
- Option B: Use `llama-cpp-python` with QLoRA support (via gguf)
- Option C: Use AWQ quantization instead via `autoawq` (may not support training)

## QLoRA Configuration

### BitsAndBytesConfig
```python
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)
```

### LoRA Config
```python
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=[
        "q_proj", "v_proj", "k_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    lora_dropout=0.1,
    bias="none",
    task_type="CAUSAL_LM",
)
```

**Rationale**:
- `r=16`: Standard for 8B models; r=8 is too low for function-calling precision, r=32 may overfit on 2.6k examples
- `alpha=32`: alpha/r = 2.0 — safe default scaling ratio
- All linear layers in attention + FFN: function-calling needs precise structured output, full LoRA on all projections helps
- `nf4` over `fp4`: better accuracy for structured output tasks
- `double_quant`: saves ~0.5GB VRAM with minimal accuracy loss

## VRAM Budget — 12GB RTX 5070

| Component | Memory (est.) |
|-----------|--------------|
| Model weights (4-bit) | ~4.5 GB |
| LoRA adapter params (gradients + optimizer) | ~0.8 GB |
| Activations (seq=512, batch=1) | ~1.5 GB |
| Attention cache | ~1.0 GB |
| Input/output buffers | ~0.5 GB |
| **Subtotal** | **~8.3 GB** |
| Headroom (other processes) | ~3.7 GB |

**Conclusion**: `per_device_train_batch_size=1` fits comfortably. Could try `per_device=2` with `gradient_checkpointing` and `gradient_accumulation=4` but batch=1 is safer on first run.

### Recommended Training Config
```python
training_args = TrainingArguments(
    per_device_train_batch_size=1,
    per_device_eval_batch_size=1,
    gradient_accumulation_steps=8,      # effective batch = 8
    gradient_checkpointing=True,
    learning_rate=2e-4,
    num_train_epochs=3,
    warmup_ratio=0.1,
    logging_steps=10,
    save_steps=200,
    eval_steps=200,
    save_strategy="steps",
    evaluation_strategy="steps",
    save_total_limit=3,
    optim="adamw_8bit",                 # saves VRAM
    fp16=False,                         # bf16 preferred for Blackwell
    bf16=True,
    max_grad_norm=0.3,
    lr_scheduler_type="cosine",
    report_to="none",
    output_dir="./checkpoints",
)
```

## Dataset Loading & Tokenization

### Approach
1. Load JSONL with `datasets.load_dataset("json", data_files="...")` 
2. 80/20 train/val split (stratified by tool name)
3. Format as ChatML using tokenizer's `apply_chat_template` with `tool_use=True` (transformers >=4.47.0)
4. Tokenize with `max_seq_length=512`, truncate/pad

**⚠️ Critical**: The dataset is in OpenAI function-calling format (assistant.tool_calls[].function.arguments as JSON string). This is NOT the native HuggingFace tool_use format. We have two options:

| Approach | Pros | Cons | Effort |
|----------|------|------|--------|
| **A. Native HF format** | Works with SFTTrainer's built-in tool handling, future-proof | Need to convert dataset format | Medium |
| **B. Custom formatting** | Keep dataset as-is, simpler code | May not leverage SFTTrainer's tool features | Low |

**Recommendation**: Approach B (custom formatting) for first iteration. Convert each example to: system prompt + user NL → serialized JSON tool_call. This is simpler and gives full control. Can upgrade to native format in v2.

### Tokenization Strategy
- Use Llama-3 tokenizer's `apply_chat_template` for the conversation structure
- Tool calls formatted as assistant response text (serialized JSON)
- Labels mask the user/system portions (standard LM loss on assistant response only)

## Training Config Alternatives

### Approach A: SFTTrainer with DataCollatorForCompletionOnlyLM
- Uses `DataCollatorForCompletionOnlyLM` with `response_template="<|start_header_id|>assistant<|end_header_id|>"`
- Labels are auto-masked for user/system turns
- **Pro**: Standard TRL pattern, well-documented
- **Con**: Requires careful construction of response template ID
- **Effort**: Medium

### Approach B: Manual training loop with Trainer
- Supply pre-tokenized dataset with `labels` column already set
- **Pro**: Full control over masking
- **Con**: More boilerplate, easy to get wrong
- **Effort**: High

### Approach C: OpenPipe / axolotl config
- Use axolotl YAML config (community standard)
- **Pro**: Declarative, reproducible, well-tested
- **Con**: Another dependency, less control
- **Effort**: Low (config) / Medium (integrate)

**Recommendation**: Approach A — SFTTrainer is the most battle-tested path for QLoRA fine-tuning. Use `DataCollatorForCompletionOnlyLM` with proper response template.

## Evaluation Metrics

### Primary Metrics
1. **Exact match** — JSON tool call matches expected output character-for-character
2. **Tool name accuracy** — correct function selected
3. **Schema conformance** — generated JSON validates against tool_definitions.json
4. **Field-level accuracy** — correct parameter values (region, instance_type, etc.)

### Metric Implementation
- Evaluate on hold-out validation set (~520 examples)
- Parse assistant response as JSON with `json.loads` (handle markdown fences)
- Validate `tool_calls[0].function.name` and `arguments` against expected
- Report: exact_match, tool_accuracy, schema_validity, field_accuracy

### Evaluation at Inference Time
- Generate with `temperature=0.1` for deterministic output
- Post-process: extract JSON from markdown code blocks if present
- Fallback: retry generation if JSON parsing fails

## Checkpointing & Export

### Checkpoint Strategy
- Save LoRA adapter only (`save_only_model=True` in SFTTrainer or custom callback)
- Checkpoints at every 200 steps, keep last 3
- Final adapter: `./checkpoints/final/`

### Export Options
| Option | Pros | Cons | Size |
|--------|------|------|------|
| **LoRA adapter only** | Small (~34MB), easy to distribute | Requires base model at inference | ~34 MB |
| **Merged model** | Self-contained inference | Large (~4.5GB merged + quantized), merging requires time | ~16 GB (fp16) |
| **GGUF conversion** | Runs on CPU/consumer GPUs, llama.cpp compatible | Extra conversion step, quality loss possible | ~4.7 GB |

**Recommendation**: Save LoRA adapter only for this phase. Merged export can be a follow-up change.

## Risks

### Critical
1. **bitsandbytes + Blackwell (sm_120) compatibility** — HIGH. The RTX 5070 may require compiling bitsandbytes from source. If 0.45+ doesn't support sm_120, we need a fallback (e.g., use `transformers` built-in 4-bit via `load_in_4bit=True` which may use different backend, or compile from source with custom arch flags).
2. **VRAM margin is thin at 12GB** — MEDIUM. Gradient checkpointing is mandatory. Must monitor with `nvidia-smi` during first training step. If OOM, reduce `max_seq_length` to 384 or use `gradient_accumulation` only (already at batch=1).

### Medium
3. **OneDrive sync churn during training** — Writes from WSL2 to the shared OneDrive folder would cause constant sync. Solution: run training entirely on WSL2 native fs, sync only final checkpoint back.
4. **PyTorch CUDA 12.8 compatibility** — Need to verify torch nightly or latest stable supports CUDA 12.8. May need to install from `pip install --pre torch --index-url https://download.pytorch.org/whl/nightly/cu128`.
5. **Spanish system prompt and dataset** — Llama-3 is primarily English-trained. The Spanish instruction format may require more epochs or lower LR to adapt. Consider evaluating on a held-out Spanish set.

### Low
6. **HuggingFace authentication** — Need a token for gated model `meta-llama/Meta-Llama-3-8B`. User must accept license at hf.co/meta-llama.
7. **Deterministic generation for eval** — Sampling approaches may introduce variance in exact-match metrics. Use deterministic decoding (temperature=0, do_sample=False) for evaluation.

## Ready for Proposal

Yes. All exploration findings are ready. The orchestrator should tell the user:

- The training pipeline is well-defined with standard QLoRA + SFTTrainer approach
- **bitsandbytes + Blackwell (sm_120) is the single biggest unknown** — needs to be validated early (propose a "smoke test" task)
- 12GB VRAM is tight but workable with per_device=1, gradient checkpointing, and bf16
- Recommend starting with SFTTrainer + DataCollatorForCompletionOnlyLM (Approach A)
- Dataset format (OpenAI tool_calls) needs custom formatting — suggest keeping as-is for v1
- WSL2 needs uv + CUDA toolkit + ML stack installed as prerequisite tasks
