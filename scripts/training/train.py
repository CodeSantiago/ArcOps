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
from datasets import DatasetDict, load_dataset
from peft import LoraConfig as PefLoraConfig
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    default_data_collator,
)
from trl import DataCollatorForCompletionOnlyLM, SFTTrainer

# Add project root so scripts/training/ can resolve imports
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.training.pipeline_utils import serialize_tool_calls
from scripts.training.train_config import TrainingConfig

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
    return parser.parse_args(argv)


def load_and_split_dataset(config: TrainingConfig) -> DatasetDict:
    """Load JSONL dataset and split into train/val/test (80/10/10).

    Args:
        config: Validated training configuration.

    Returns:
        A DatasetDict with ``train``, ``val``, and ``test`` splits.
    """
    log.info("Loading dataset from %s", config.data.train_file)
    dataset = load_dataset("json", data_files=config.data.train_file, split="all")

    # 80/20 split
    first_split = dataset.train_test_split(test_size=0.2, seed=config.data.seed)
    train = first_split["train"]

    # 20 -> 10/10 (val/test)
    second_split = first_split["test"].train_test_split(test_size=0.5, seed=config.data.seed)

    log.info("Dataset splits: train=%d, val=%d, test=%d", len(train), len(second_split["train"]), len(second_split["test"]))
    return DatasetDict({
        "train": train,
        "val": second_split["train"],
        "test": second_split["test"],
    })


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
    # Debug: print type and first few elements
    if isinstance(messages_raw[0], list):
        log.warning("Messages format is list-of-lists, converting...")
        keys = ["role", "content"]
        messages = [dict(zip(keys, m[:2])) for m in messages_raw]
        # Handle tool_calls separately (3rd element if present)
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

    # 2. Load and split dataset
    dataset = load_and_split_dataset(config)

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

    # 6. Build data collator (labels only on assistant responses)
    response_template = "<|im_start|>assistant"
    collator = DataCollatorForCompletionOnlyLM(
        response_template=response_template,
        tokenizer=tokenizer,
    )

    # 7. Pre-process dataset: format + tokenize
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
        result = tokenizer(example["text"], truncation=True, max_length=config.training.max_seq_length, padding="max_length")
        result["labels"] = result["input_ids"].copy()
        return result

    dataset = dataset.map(_tokenize, remove_columns=["text"])

    # 8. Create SFTTrainer with pre-tokenized dataset
    tokenizer.model_max_length = config.training.max_seq_length
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["val"],
        tokenizer=tokenizer,
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
        log_path.write_text(json.dumps(trainer.state.log_history, indent=2, default=str), encoding="utf-8")
        log.info("Training metrics saved to %s", log_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
