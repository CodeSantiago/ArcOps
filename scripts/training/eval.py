"""Evaluation script for the CloudOps function-calling QLoRA model.

Usage:
    uv run python scripts/training/eval.py --checkpoint checkpoints/final

Loads the trained LoRA adapter + base model, runs inference on the test
split of the dataset, and reports metrics:
    - Exact-match accuracy (tool name + all arguments)
    - Tool-name accuracy
    - Field-level argument accuracy
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import torch
from datasets import load_dataset
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

# Add project root so scripts/training/ can resolve imports
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.training.pipeline_utils import (
    compute_exact_match,
    compute_field_accuracy,
    compute_tool_name_accuracy,
    parse_tool_call,
    serialize_tool_calls,
)
from scripts.training.train_config import TrainingConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eval")

# Default config — used to find the dataset path and seed when no explicit
# config is provided via CLI.
_DEFAULT_CONFIG = _PROJECT_ROOT / "scripts" / "training" / "default_config.yaml"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Evaluate QLoRA fine-tuned model")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        required=True,
        help="Path to the saved LoRA adapter directory",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG,
        help="Path to YAML config (default: %(default)s)",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=256,
        help="Max tokens to generate per example (default: %(default)s)",
    )
    return parser.parse_args(argv)


def load_test_split(config: TrainingConfig) -> list[dict]:
    """Load the test split (10% holdout) from the training dataset.

    Uses the same train_test_split logic as train.py to ensure the same
    partition is reproduced for evaluation.
    """
    dataset = load_dataset("json", data_files=config.data.train_file, split="all")
    first_split = dataset.train_test_split(test_size=0.2, seed=config.data.seed)
    second_split = first_split["test"].train_test_split(test_size=0.5, seed=config.data.seed)
    log.info("Test split: %d examples", len(second_split["test"]))
    return list(second_split["test"])


def generate_tool_call(
    messages: list[dict],
    model: AutoModelForCausalLM | PeftModel,
    tokenizer: AutoTokenizer,
    max_new_tokens: int,
) -> str:
    """Generate a tool-call response for the conversation prefix.

    The assistant response is *excluded* from the prompt — the model
    must generate it.
    """
    conversation = serialize_tool_calls(messages)
    # Remove the last assistant message if present (we want the model to generate it)
    if conversation and conversation[-1]["role"] == "assistant":
        prompt_messages = conversation[:-1]
    else:
        prompt_messages = conversation

    inputs = tokenizer.apply_chat_template(
        prompt_messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
    ).to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            inputs.input_ids if hasattr(inputs, "input_ids") else inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )

    generated = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    )
    return generated.strip()


def extract_reference_tool_call(messages: list[dict]) -> dict | None:
    """Extract the expected tool call from the assistant message.

    Returns a normalised dict with ``name`` and ``arguments`` keys,
    or ``None`` if no tool call is present.
    """
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            tcs = msg["tool_calls"]
            if tcs:
                func = tcs[0].get("function", {})
                name = func.get("name", "")
                raw_args = func.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except (json.JSONDecodeError, TypeError):
                    args = {}
                return {"name": name, "arguments": args}
    return None


def evaluate(
    test_examples: list[dict],
    model: AutoModelForCausalLM | PeftModel,
    tokenizer: AutoTokenizer,
    max_new_tokens: int,
) -> dict:
    """Run evaluation on the test set and return aggregated metrics.

    Returns a dict with per-example results and summary metrics.
    """
    results: list[dict] = []
    exact_matches = 0
    correct_tool_names = 0
    field_accuracies: list[float] = []

    for i, example in enumerate(test_examples):
        messages = example["messages"]
        reference = extract_reference_tool_call(messages)

        if reference is None:
            continue  # skip examples without tool calls

        generated = generate_tool_call(messages, model, tokenizer, max_new_tokens)
        predicted = parse_tool_call(generated)

        if predicted is None:
            exact_matches += 0
            correct_tool_names += 0
            field_accuracies.append(0.0)
            results.append({
                "index": i,
                "expected": reference,
                "predicted": None,
                "exact_match": False,
                "tool_name_correct": False,
                "field_accuracy": 0.0,
            })
            continue

        em = compute_exact_match(predicted, reference)
        tn = compute_tool_name_accuracy(predicted["name"], reference["name"])
        fa = compute_field_accuracy(predicted["arguments"], reference["arguments"])

        if em:
            exact_matches += 1
        if tn == 1.0:
            correct_tool_names += 1
        field_accuracies.append(fa)

        results.append({
            "index": i,
            "expected": reference,
            "predicted": predicted,
            "generated_raw": generated[:500],
            "exact_match": em,
            "tool_name_correct": bool(tn),
            "field_accuracy": fa,
        })

    n = len(results)
    summary = {
        "num_examples": n,
        "exact_match_accuracy": round(exact_matches / n, 4) if n else 0.0,
        "tool_name_accuracy": round(correct_tool_names / n, 4) if n else 0.0,
        "field_accuracy_mean": round(sum(field_accuracies) / n, 4) if n else 0.0,
        "num_exact_matches": exact_matches,
        "num_correct_tool_names": correct_tool_names,
    }

    return {"summary": summary, "results": results}


def print_report(metrics: dict) -> None:
    """Print a human-readable evaluation report."""
    s = metrics["summary"]
    border = "=" * 60
    print(f"\n{border}")
    print("  EVALUATION REPORT")
    print(border)
    print(f"  Examples evaluated:  {s['num_examples']}")
    print(f"  Exact-match acc:     {s['exact_match_accuracy']:.2%}")
    print(f"  Tool-name acc:       {s['tool_name_accuracy']:.2%}")
    print(f"  Field accuracy mean: {s['field_accuracy_mean']:.2%}")
    print(f"  Exact matches:       {s['num_exact_matches']}/{s['num_examples']}")
    print(f"  Correct tool names:  {s['num_correct_tool_names']}/{s['num_examples']}")
    print(border)

    # Show a few example predictions
    print("\n  Sample predictions (first 5):")
    for r in metrics["results"][:5]:
        expected_name = r["expected"]["name"]
        predicted_name = r["predicted"]["name"] if r["predicted"] else "N/A"
        em = "✓" if r["exact_match"] else "✗"
        print(f"  [{em}] expected={expected_name:30s} predicted={predicted_name:30s}")


def main(argv: list[str] | None = None) -> int:
    """Run evaluation."""
    args = parse_args(argv)

    adapter_path = args.checkpoint
    if not (adapter_path / "adapter_config.json").is_file():
        log.error("No LoRA adapter found at %s", adapter_path)
        log.error("Expected adapter_config.json in that directory.")
        return 1

    # 1. Load config
    config = TrainingConfig.from_yaml(args.config)

    # 2. Load test split
    test_examples = load_test_split(config)

    # 3. Load base model with 4-bit quantization
    log.info("Loading base model (4-bit)...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        config.model.name,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        trust_remote_code=False,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        config.model.name,
        trust_remote_code=False,
    )
    tokenizer.pad_token = tokenizer.eos_token

    # 4. Load LoRA adapter with CPU offloading for VRAM-constrained eval
    log.info("Loading adapter from %s", adapter_path)
    model = PeftModel.from_pretrained(model, adapter_path, offload_folder="offload")
    model.eval()

    # 5. Run evaluation
    log.info("Evaluating on %d test examples...", len(test_examples))
    metrics = evaluate(test_examples, model, tokenizer, args.max_new_tokens)

    # 6. Print and save report
    print_report(metrics)

    report_path = adapter_path.parent / "eval_report.json"
    report_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Report saved to %s", report_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
