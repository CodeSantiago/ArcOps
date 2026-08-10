"""QLoRA fine-tuning entrypoint for CloudOps function-calling model.

Usage:
    uv run python scripts/training/train.py --config scripts/training/default_config.yaml

Loads a HuggingFace model in 4-bit (QLoRA), applies LoRA adapters,
trains with SFTTrainer on a JSONL dataset of tool-call conversations,
and saves the adapter weights to the configured output directory.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import torch
from datasets import Dataset, DatasetDict
from peft import LoraConfig as PefLoraConfig
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    default_data_collator,
)
from trl import SFTTrainer

# Add project root so scripts/training/ can resolve imports
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.training.pipeline_utils import (  # noqa: E402
    build_completion_labels,
    build_splits,
    serialize_tool_calls,
)
from scripts.training.template_families import (  # noqa: E402
    KNOWN_FAMILIES,
    parse_unseen_values,
    split_file_by_template_family,
    split_file_by_unseen_values,
)
from scripts.training.train_config import TrainingConfig  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("train")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="QLoRA fine-tuning for CloudOps function calling")
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to YAML config file (see default_config.yaml)",
    )
    parser.add_argument(
        "--split-mode",
        choices=["standard", "template", "unseen"],
        default="standard",
        help=(
            "Dataset partitioning (default: %(default)s). "
            "standard = deduplicated 80/10/10 random split. "
            "template = train only on families NOT held out for test "
            "(--test-families). "
            "unseen = train only on examples that do NOT contain the "
            "configured unseen values (--unseen)."
        ),
    )
    parser.add_argument(
        "--test-families",
        default=None,
        help=(
            "Comma-separated template families to EXCLUDE from training "
            "(required with --split-mode template). "
            f"Known families: {', '.join(KNOWN_FAMILIES)}"
        ),
    )
    parser.add_argument(
        "--unseen",
        action="append",
        default=[],
        metavar="FIELD=value1,value2",
        help=(
            "Unseen-value holdout (repeatable, required with --split-mode unseen). "
            "Examples carrying these values are excluded from training. "
            "Fields: region, instance_type, db, port."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=(
            "Split seed for template/unseen modes. Defaults to the config's "
            "data.seed. Must match the seed used during evaluation."
        ),
    )
    return parser.parse_args(argv)


def load_and_split_dataset(
    config: TrainingConfig,
    split_mode: str = "standard",
    test_families: str | None = None,
    unseen: list[str] | None = None,
    seed: int | None = None,
) -> tuple[DatasetDict, dict]:
    """Load JSONL dataset, deduplicate, and split into train/val(/test).

    Duplicate examples are removed BEFORE the split by canonical
    ``(prompt, tool name, parsed arguments)`` key, so the same row can never
    land in both train and test (no train/test leakage). The split is seeded
    and reproducible; the returned metadata reports dataset size, unique row
    count, duplicate count, split seed, and overlap/leakage detection.

    ``split_mode``:
    - ``standard``: 80/10/10 random split (the historical partition).
    - ``template``: complete template families (``--test-families``) are
      excluded from training entirely — the model never sees their phrasing.
    - ``unseen``: examples containing configured values (``--unseen``) are
      excluded from training — the model never sees those values.

    Only ``train``/``val`` are returned to the trainer; the held-out test
    partition is produced by eval.py from the SAME split call.

    Args:
        config: Validated training configuration.
        split_mode: Which partitioning to use (standard/template/unseen).
        test_families: Comma-separated families to exclude (template mode).
        unseen: ``FIELD=value1,value2`` items to exclude (unseen mode).

    Returns:
        A tuple of ``(DatasetDict, metadata)`` with ``train`` and ``val``
        splits plus integrity metadata.
    """
    log.info("Loading dataset from %s (split-mode=%s)", config.data.train_file, split_mode)
    split_seed = seed if seed is not None else config.data.seed

    if split_mode == "standard":
        splits, metadata = build_splits(config.data.train_file, config.data.seed)
    elif split_mode == "template":
        if not test_families:
            raise ValueError(
                "--split-mode template requires --test-families "
                "(comma-separated family names)"
            )
        families = [f.strip() for f in test_families.split(",") if f.strip()]
        splits, metadata = split_file_by_template_family(
            config.data.train_file, families, seed=split_seed
        )
        log.info(
            "Template holdout: train=%d val=%d | EXCLUDED test families=%s",
            metadata["train_size"],
            metadata["val_size"],
            ",".join(metadata["test_families"]),
        )
    elif split_mode == "unseen":
        if not unseen:
            raise ValueError(
                "--split-mode unseen requires at least one --unseen FIELD=value1,value2"
            )
        splits, metadata = split_file_by_unseen_values(
            config.data.train_file, parse_unseen_values(unseen), seed=split_seed
        )
        log.info(
            "Unseen-value holdout: train=%d val=%d | EXCLUDED unseen=%s",
            metadata["train_size"],
            metadata["val_size"],
            metadata["unseen_values"],
        )
    else:
        raise ValueError(f"Unknown split mode: {split_mode}")

    log.info(
        "Dataset integrity: total=%d unique=%d duplicates=%d",
        metadata["dataset_size"],
        metadata["unique_after_dedup"],
        metadata["duplicate_count"],
    )
    if split_mode == "standard":
        log.info(
            "Splits: train=%d, val=%d, test=%d (seed=%d, overlap=%d, leakage=%s)",
            metadata["train_size"],
            metadata["val_size"],
            metadata["test_size"],
            metadata["split_seed"],
            metadata["train_test_overlap_count"],
            metadata["leakage_detected"],
        )
    dataset = DatasetDict({
        "train": Dataset.from_list(splits["train"]),
        "val": Dataset.from_list(splits["val"]),
    })
    return dataset, metadata


def build_bnb_config(config: TrainingConfig) -> BitsAndBytesConfig:
    """Build BitsAndBytes 4-bit quantization config."""
    dtype_map = {"bf16": torch.bfloat16, "fp16": torch.float16, "float32": torch.float32}
    compute_dtype = dtype_map.get(config.model.bnb_4bit_compute_dtype, torch.bfloat16)

    return BitsAndBytesConfig(
        load_in_4bit=config.model.load_in_4bit,
        bnb_4bit_quant_type=config.model.bnb_4bit_quant_type,
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=config.model.bnb_4bit_use_double_quant,
    )


def build_training_args(config: TrainingConfig, output_dir: Path) -> TrainingArguments:
    """Build HuggingFace TrainingArguments from the config model."""
    kwargs: dict = dict(
        output_dir=str(output_dir),
        per_device_train_batch_size=config.training.per_device_train_batch_size,
        per_device_eval_batch_size=config.training.per_device_eval_batch_size,
        gradient_accumulation_steps=config.training.gradient_accumulation_steps,
        gradient_checkpointing=config.training.gradient_checkpointing,
        learning_rate=config.training.learning_rate,
        num_train_epochs=config.training.num_train_epochs,
        warmup_ratio=config.training.warmup_ratio,
        logging_steps=config.training.logging_steps,
        save_strategy=config.training.save_strategy,
        eval_strategy=config.training.eval_strategy,
        save_total_limit=config.training.save_total_limit,
        optim=config.training.optim,
        bf16=config.training.bf16,
        max_grad_norm=config.training.max_grad_norm,
        lr_scheduler_type=config.training.lr_scheduler_type,
        report_to=config.training.report_to,
        hub_token=None,
        remove_unused_columns=False,
        dataloader_num_workers=0,
    )

    # Add step-based overrides when strategy is not "epoch"
    if config.training.save_strategy == "steps" and config.training.save_steps is not None:
        kwargs["save_steps"] = config.training.save_steps
    if config.training.eval_strategy == "steps" and config.training.eval_steps is not None:
        kwargs["eval_steps"] = config.training.eval_steps

    return TrainingArguments(**kwargs)


def formatting_func(example: dict, tokenizer: AutoTokenizer) -> str:
    """Convert a dataset example to formatted ChatML text.

    * Serialises any ``tool_calls`` in the assistant message to text.
    * Applies the tokenizer's chat template to produce the full prompt.

    Args:
        example: A single dataset row with a ``messages`` key.
        tokenizer: The model's tokenizer.

    Returns:
        A ChatML-formatted string ready for tokenization.
    """
    messages_raw = example["messages"]
    if isinstance(messages_raw[0], list):
        keys = ["role", "content"]
        messages = [dict(zip(keys, m[:2])) for m in messages_raw]
        for i, m in enumerate(messages_raw):
            if len(m) > 2 and m[2] is not None:
                messages[i]["tool_calls"] = m[2]
    else:
        messages = messages_raw
    messages = serialize_tool_calls(messages)
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the QLoRA training pipeline."""
    args = parse_args(argv)

    # 1. Load config
    config = TrainingConfig.from_yaml(args.config)
    output_dir = Path(config.training.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("Config loaded from %s", args.config)

    # 2. Load, deduplicate, and split dataset
    dataset, dataset_metadata = load_and_split_dataset(
        config,
        split_mode=args.split_mode,
        test_families=args.test_families,
        unseen=args.unseen,
        seed=args.seed,
    )

    # Persist dataset-integrity metadata next to the training output so
    # evaluation reports can include it (see eval.py).
    import json as _json

    dataset_metadata["mode"] = args.split_mode
    if args.split_mode == "template":
        dataset_metadata["test_families"] = (
            [f.strip() for f in args.test_families.split(",") if f.strip()]
            if args.test_families else []
        )
    if args.split_mode == "unseen":
        dataset_metadata["unseen_values"] = dataset_metadata.get("unseen_values") or {}

    meta_path = output_dir / "dataset_metadata.json"
    meta_path.write_text(
        _json.dumps(dataset_metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Dataset integrity metadata saved to %s", meta_path)

    # 3. Build 4-bit config + load model
    bnb_config = build_bnb_config(config)
    log.info("Loading model: %s", config.model.name)
    model = AutoModelForCausalLM.from_pretrained(
        config.model.name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=False,
    )

    tokenizer = AutoTokenizer.from_pretrained(
        config.model.name,
        trust_remote_code=False,
    )
    tokenizer.pad_token = tokenizer.eos_token
    log.info("Model and tokenizer loaded")

    # 4. Build LoRA config
    peft_config = PefLoraConfig(
        r=config.lora.r,
        lora_alpha=config.lora.lora_alpha,
        target_modules=config.lora.target_modules,
        lora_dropout=config.lora.lora_dropout,
        bias=config.lora.bias,
        task_type="CAUSAL_LM",
    )

    # 5. Build training arguments
    training_args = build_training_args(config, output_dir)

    # 6. Pre-process dataset: format + tokenize with masked labels
    response_marker = "<|im_start|>assistant"
    marker_ids = tokenizer.encode(response_marker, add_special_tokens=False)
    pad_token_id = tokenizer.pad_token_id

    def _format(example: dict) -> dict:
        messages_raw = example["messages"]
        if isinstance(messages_raw[0], list):
            keys = ["role", "content"]
            messages = [dict(zip(keys, m[:2])) for m in messages_raw]
            for i, m in enumerate(messages_raw):
                if len(m) > 2 and m[2] is not None:
                    messages[i]["tool_calls"] = m[2]
        else:
            messages = messages_raw
        messages = serialize_tool_calls(messages)
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        return {"text": text}

    dataset = dataset.map(_format, remove_columns=dataset["train"].column_names)

    def _tokenize(example: dict) -> dict:
        result = tokenizer(
            example["text"],
            truncation=True,
            max_length=config.training.max_seq_length,
            padding="max_length",
        )
        # Labels are masked to the assistant/tool-call response only; system,
        # user, and padding tokens are set to -100 so the model never trains
        # on them.
        result["labels"] = build_completion_labels(
            result["input_ids"],
            marker_ids,
            pad_token_id=pad_token_id,
        )
        return result

    dataset = dataset.map(_tokenize, remove_columns=["text"])

    # 8. Create SFTTrainer with pre-tokenized dataset
    # TRL >= 0.15 renamed the `tokenizer` kwarg to `processing_class`;
    # a PreTrainedTokenizerBase is accepted directly as processing_class.
    tokenizer.model_max_length = config.training.max_seq_length
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["val"],
        processing_class=tokenizer,
        data_collator=default_data_collator,
        peft_config=peft_config,
    )

    # 9. Train
    log.info("Starting training...")
    trainer.train()

    # 9. Save LoRA adapter only
    adapter_path = output_dir / "final"
    trainer.save_model(str(adapter_path))
    log.info("Adapter saved to %s", adapter_path)

    # Save training metrics
    log_path = output_dir / "training_metrics.json"
    if trainer.state.log_history:
        import json
        log_path.write_text(
            json.dumps(trainer.state.log_history, indent=2, default=str),
            encoding="utf-8",
        )
        log.info("Training metrics saved to %s", log_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
