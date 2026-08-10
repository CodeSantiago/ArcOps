"""Evaluation script for the CloudOps function-calling QLoRA model.

Usage:
    uv run python scripts/training/eval.py --checkpoint checkpoints/final
    uv run python scripts/training/eval.py --checkpoint checkpoints/final \
        --eval-mode template --test-families ec2_ports,rds_failover
    uv run python scripts/training/eval.py --checkpoint checkpoints/final \
        --eval-mode unseen --unseen region=ca-central-1,ap-northeast-1
    uv run python scripts/training/eval.py --checkpoint checkpoints/final \
        --eval-mode challenge

Loads the trained LoRA adapter + base model, runs inference on the requested
evaluation set, and reports metrics:
    - Exact-match accuracy (tool name + all arguments)
    - Tool-name accuracy
    - Field-level argument accuracy

Modes (``--eval-mode``):
    - ``standard``  : deduplicated 80/10/10 seeded split (in-distribution).
    - ``template``  : complete template families held out for test.
    - ``unseen``    : strict value holdout (region/instance_type/db/port).
    - ``challenge`` : manual, non-template prompts (generalization).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

# Add project root so scripts/training/ can resolve imports
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.training.pipeline_utils import (  # noqa: E402
    build_splits,
    compute_exact_match,
    compute_field_accuracy,
    compute_tool_name_accuracy,
    extract_tool_call,
    load_jsonl,
    parse_tool_call,
    serialize_tool_calls,
)
from scripts.training.template_families import (  # noqa: E402
    KNOWN_FAMILIES,
    parse_unseen_values,
    split_file_by_template_family,
    split_file_by_unseen_values,
    validate_challenge_set,
)
from scripts.training.train_config import TrainingConfig  # noqa: E402

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
    parser.add_argument(
        "--eval-mode",
        choices=["standard", "template", "unseen", "challenge"],
        default="standard",
        help=(
            "Which evaluation protocol to run (default: %(default)s). "
            "standard = deduplicated 80/10/10 random split (in-distribution). "
            "template = hold out COMPLETE template families for test. "
            "unseen = strict holdout where configured region/instance_type/db/port "
            "values appear only in test. "
            "challenge = manually authored, non-template prompts."
        ),
    )
    parser.add_argument(
        "--test-families",
        default=None,
        help=(
            "Comma-separated template families to hold out for test "
            "(required with --eval-mode template). "
            f"Known families: {', '.join(KNOWN_FAMILIES)}"
        ),
    )
    parser.add_argument(
        "--unseen",
        action="append",
        default=[],
        metavar="FIELD=value1,value2",
        help=(
            "Unseen-value holdout (repeatable, required with --eval-mode unseen). "
            "Fields: region, instance_type, db, port. "
            "Example: --unseen region=ca-central-1,ap-northeast-1 --unseen port=6379"
        ),
    )
    parser.add_argument(
        "--challenge-file",
        type=Path,
        default=_PROJECT_ROOT / "data" / "challenge_set.jsonl",
        help="Path to the manual challenge set (default: %(default)s)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=(
            "Split seed for template/unseen modes. Defaults to the config's "
            "data.seed. Must match the seed used during training."
        ),
    )
    return parser.parse_args(argv)


def load_test_split(config: TrainingConfig) -> tuple[list[dict], dict]:
    """Load the test split (10% holdout) from the training dataset.

    Uses the exact same deduplication + seeded split path as train.py
    (``pipeline_utils.build_splits``), so the test partition is identical to
    the one used during training and no duplicate row can leak across splits.

    Returns ``(test_examples, metadata)`` where metadata reports dataset
    size, unique rows, duplicate count, split seed, train/test overlap, and
    whether duplicate leakage was detected.
    """
    splits, metadata = build_splits(config.data.train_file, config.data.seed)
    log.info(
        "Dataset integrity: size=%d unique=%d duplicates=%d",
        metadata["dataset_size"],
        metadata["unique_after_dedup"],
        metadata["duplicate_count"],
    )
    log.info(
        "Test split: %d examples (seed=%d, overlap=%d, leakage=%s)",
        metadata["test_size"],
        metadata["split_seed"],
        metadata["train_test_overlap_count"],
        metadata["leakage_detected"],
    )
    return list(splits["test"]), metadata


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
    return extract_tool_call(messages)


def load_evaluation_set(
    config: TrainingConfig, args: argparse.Namespace
) -> tuple[list[dict], dict]:
    """Load the evaluation set for the requested ``--eval-mode``.

    Returns ``(test_examples, metadata)`` where metadata is mode-specific:

    - ``standard``: deduplicated 80/10/10 seeded split — the in-distribution
      metric. Identical partition to train.py (shared code path).
    - ``template``: complete template families held out for test.
    - ``unseen``: strict value-based holdout (region/instance_type/db/port).
    - ``challenge``: the manual, non-template challenge set.

    Raises ``ValueError`` when required mode arguments are missing.
    """
    if args.eval_mode == "standard":
        examples, meta = load_test_split(config)
        meta["mode"] = "standard"
        return examples, meta

    if args.eval_mode == "template":
        if not args.test_families:
            raise ValueError(
                "--eval-mode template requires --test-families "
                "(comma-separated family names, e.g. ec2_ports,rds_failover)"
            )
        families = [f.strip() for f in args.test_families.split(",") if f.strip()]
        seed = args.seed if args.seed is not None else config.data.seed
        splits, metadata = split_file_by_template_family(
            config.data.train_file, families, seed=seed
        )
        metadata["mode"] = "template"
        log.info(
            "Template holdout: test=%d train=%d val=%d | test families=%s",
            metadata["test_size"],
            metadata["train_size"],
            metadata["val_size"],
            ",".join(metadata["test_families"]),
        )
        return list(splits["test"]), metadata

    if args.eval_mode == "unseen":
        if not args.unseen:
            raise ValueError(
                "--eval-mode unseen requires at least one --unseen FIELD=value1,value2 "
                "(e.g. --unseen region=ca-central-1,ap-northeast-1)"
            )
        unseen = parse_unseen_values(args.unseen)
        seed = args.seed if args.seed is not None else config.data.seed
        splits, metadata = split_file_by_unseen_values(
            config.data.train_file, unseen, seed=seed
        )
        metadata["mode"] = "unseen"

        # Warn about vacuous holdouts: a configured unseen value that never
        # appears anywhere in the dataset cannot be tested.
        all_examples = load_jsonl(str(config.data.train_file))
        from scripts.training.template_families import extract_arg_values

        def _args(ex: dict) -> dict:
            tool_call = extract_tool_call(ex.get("messages") or [])
            a = tool_call.get("arguments") if tool_call else None
            return a if isinstance(a, dict) else {}

        vacuous = []
        for field, values in (metadata.get("unseen_values") or {}).items():
            for value in values:
                total = sum(
                    1
                    for ex in all_examples
                    if value in extract_arg_values(_args(ex), field)
                )
                if total == 0:
                    vacuous.append(f"{field}={value}")
        if vacuous:
            log.warning(
                "VACUOUS HOLD-OUT: these configured unseen values never appear in "
                "the dataset: %s. The resulting metric does NOT test generalization "
                "to those values.",
                ", ".join(vacuous),
            )
            metadata["vacuous_holdout"] = vacuous
        log.info(
            "Unseen-value holdout: test=%d train=%d val=%d | unseen=%s",
            metadata["test_size"],
            metadata["train_size"],
            metadata["val_size"],
            metadata["unseen_values"],
        )
        return list(splits["test"]), metadata

    if args.eval_mode == "challenge":
        path = args.challenge_file
        if not path.is_file():
            raise FileNotFoundError(f"Challenge set not found: {path}")
        examples = load_jsonl(str(path))
        errors = validate_challenge_set(examples)
        if errors:
            raise ValueError(
                f"Challenge set {path} failed validation ({len(errors)} errors): "
                f"{errors[0]}"
            )
        metadata = {
            "mode": "challenge",
            "challenge_file": str(path),
            "num_examples": len(examples),
        }
        log.info("Challenge set: %d examples from %s", len(examples), path)
        return examples, metadata

    raise ValueError(f"Unknown eval mode: {args.eval_mode}")


def load_training_metadata(adapter_path: Path) -> dict | None:
    """Load ``dataset_metadata.json`` written by train.py, if present.

    The file lives next to the adapter (e.g. ``checkpoints/dataset_metadata.json``).
    """
    meta_path = adapter_path.parent / "dataset_metadata.json"
    if not meta_path.is_file():
        log.warning("No training dataset_metadata.json found at %s", meta_path)
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not parse %s: %s", meta_path, exc)
        return None


def verify_split_consistency(
    training_meta: dict | None,
    args: argparse.Namespace,
    eval_meta: dict,
) -> None:
    """Refuse template/unseen evaluation when training split does not match.

    Prevents the "evaluate examples the model already saw" leak that can make
    template/unseen metrics misleadingly perfect.
    """
    if args.eval_mode == "challenge":
        return  # manual set is independent of training partition

    if training_meta is None:
        log.warning(
            "Cannot verify split consistency: no training metadata. "
            "Treat %s results with caution.",
            args.eval_mode,
        )
        return

    train_mode = training_meta.get("mode") or training_meta.get("split_mode") or "standard"
    train_seed = training_meta.get("split_seed")

    if args.eval_mode != train_mode:
        raise ValueError(
            f"Evaluation split does not match training split: "
            f"model was trained with mode={train_mode!r} seed={train_seed}, "
            f"but evaluation requested mode={args.eval_mode!r} seed={args.seed}. "
            f"Re-train with the matching split mode before running this evaluation."
        )

    if train_seed is not None and args.seed != train_seed:
        raise ValueError(
            f"Seed mismatch: training used seed={train_seed}, "
            f"evaluation requested seed={args.seed}."
        )

    if args.eval_mode == "template":
        train_families = set(training_meta.get("test_families") or [])
        eval_families = set(eval_meta.get("test_families") or [])
        if train_families != eval_families:
            raise ValueError(
                f"Template families mismatch: training held out {sorted(train_families)}, "
                f"evaluation requested {sorted(eval_families)}."
            )

    if args.eval_mode == "unseen":
        train_unseen = training_meta.get("unseen_values") or {}
        eval_unseen = eval_meta.get("unseen_values") or {}
        if train_unseen != eval_unseen:
            raise ValueError(
                f"Unseen values mismatch: training used {train_unseen}, "
                f"evaluation requested {eval_unseen}."
            )


def evaluate(
    test_examples: list[dict],
    model: AutoModelForCausalLM | PeftModel,
    tokenizer: AutoTokenizer,
    max_new_tokens: int,
    metadata: dict | None = None,
) -> dict:
    """Run evaluation on the test set and return aggregated metrics.

    Args:
        test_examples: The test split (from ``load_test_split``).
        model: The (adapter-merged) model to evaluate.
        tokenizer: The model tokenizer.
        max_new_tokens: Tokens to generate per example.
        metadata: Dataset-integrity metadata included in the report
            (dataset size, unique rows, duplicate count, split seed,
            train/test overlap, leakage detection).

    Returns:
        A dict with per-example results, summary metrics, and metadata.
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

    return {
        "summary": summary,
        "results": results,
        "metadata": metadata or {},
    }


def print_report(metrics: dict) -> None:
    """Print a human-readable evaluation report."""
    s = metrics["summary"]
    meta = metrics.get("metadata") or {}
    border = "=" * 60
    print(f"\n{border}")
    print("  EVALUATION REPORT")
    print(border)
    mode = meta.get("mode", "standard")
    print(f"  Evaluation mode:     {mode}")
    print(f"  Examples evaluated:  {s['num_examples']}")
    print(f"  Exact-match acc:     {s['exact_match_accuracy']:.2%}")
    print(f"  Tool-name acc:       {s['tool_name_accuracy']:.2%}")
    print(f"  Field accuracy mean: {s['field_accuracy_mean']:.2%}")
    print(f"  Exact matches:       {s['num_exact_matches']}/{s['num_examples']}")
    print(f"  Correct tool names:  {s['num_correct_tool_names']}/{s['num_examples']}")
    print(border)

    if mode == "template":
        print("\n  Template holdout:")
        print(f"    Test families:    {', '.join(meta.get('test_families', []))}")
        print(f"    Train families:   {', '.join(meta.get('train_families', []))}")
        print(f"    Split: train={meta.get('train_size')} val={meta.get('val_size')} "
              f"test={meta.get('test_size')} (seed={meta.get('split_seed')})")
        print(f"    Family leakage:   {meta.get('leakage_detected')}")
        print(border)
    elif mode == "unseen":
        print("\n  Unseen-value holdout:")
        for field, values in (meta.get("unseen_values") or {}).items():
            print(f"    {field}: {', '.join(values)}")
        print(f"    Split: train={meta.get('train_size')} val={meta.get('val_size')} "
              f"test={meta.get('test_size')} (seed={meta.get('split_seed')})")
        violations = meta.get("unseen_value_violations") or {}
        print(f"    Strict violations (unseen value in train/val): {violations or 'none'}")
        print(border)
    elif mode == "challenge":
        print("\n  Manual challenge set (generalization, not from templates):")
        print(f"    File: {meta.get('challenge_file')}")
        print(f"    Rows: {meta.get('num_examples')}")
        print(border)

    if meta and mode == "standard":
        print("\n  Dataset integrity:")
        print(f"    Dataset size:      {meta.get('dataset_size', 'n/a')}")
        print(f"    Unique rows:       {meta.get('unique_after_dedup', 'n/a')}")
        print(f"    Duplicate count:   {meta.get('duplicate_count', 'n/a')}")
        print(f"    Split seed:        {meta.get('split_seed', 'n/a')}")
        print(f"    Train/test overlap:{meta.get('train_test_overlap_count', 'n/a')}")
        print(f"    Leakage detected:  {meta.get('leakage_detected', 'n/a')}")
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

    # 2. Load the evaluation set for the requested mode
    test_examples, metadata = load_evaluation_set(config, args)

    # 2b. Refuse template/unseen when training split does not match
    training_meta = load_training_metadata(adapter_path)
    verify_split_consistency(training_meta, args, metadata)

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
    log.info("Evaluating on %d examples (%s mode)...", len(test_examples), args.eval_mode)
    metrics = evaluate(test_examples, model, tokenizer, args.max_new_tokens, metadata=metadata)

    # 6. Print and save report
    print_report(metrics)

    report_path = adapter_path.parent / f"eval_report_{args.eval_mode}.json"
    report_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Report saved to %s", report_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
