"""Pure utility functions for the QLoRA training pipeline.

These functions have NO dependencies on torch, transformers, or other
heavy ML libraries — they are pure Python and easily unit-testable.
"""

from __future__ import annotations

import json
import random
import re
from typing import Any


def serialize_tool_calls(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-style ``tool_calls`` in assistant messages to text content.

    The dataset stores assistant responses as ``tool_calls`` (function name +
    JSON-encoded arguments).  SFT training needs the response as plain text
    content so that ``tokenizer.apply_chat_template()`` and
    ``DataCollatorForCompletionOnlyLM`` can work with it.

    Args:
        messages: List of message dicts with ``role``, ``content``,
            and optionally ``tool_calls`` keys.

    Returns:
        A new list where every assistant message that had ``tool_calls``
        now has the tool call serialised as JSON in ``content``.
    """
    result: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "assistant" and "tool_calls" in msg:
            serialized = _serialize_tool_call_list(msg["tool_calls"])
            result.append({"role": "assistant", "content": serialized})
        else:
            result.append(dict(msg))  # shallow copy
    return result


def _serialize_tool_call_list(tool_calls: list[dict]) -> str:
    """Serialize a list of tool call dicts to a JSON string.

    Each tool call in the dataset has the structure::

        {"type": "function", "function": {"name": "...", "arguments": "..."}}

    This converts them to::

        {"name": "...", "arguments": {...}}
    """
    if not tool_calls:
        return ""
    serialized_calls = []
    for tc in tool_calls:
        func = tc.get("function", {})
        name = func.get("name", "")
        raw_args = func.get("arguments", "{}")
        try:
            parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except (json.JSONDecodeError, TypeError):
            parsed_args = {}
        serialized_calls.append({"name": name, "arguments": parsed_args})

    if len(serialized_calls) == 1:
        return json.dumps(serialized_calls[0], ensure_ascii=False, sort_keys=True)
    return json.dumps(serialized_calls, ensure_ascii=False, sort_keys=True)


def parse_tool_call(text: str) -> dict | None:
    """Extract a tool-call JSON object from generated text.

    Handles:
    - Plain JSON objects at the start of the string.
    - JSON inside triple-backtick code fences (`` ```json ... ``` ``).
    - JSON embedded within surrounding natural-language text.

    Returns:
        A dict with at least ``name`` and ``arguments`` keys, or ``None``
        if no valid JSON tool call could be extracted.
    """
    candidates = _find_json_objects(text)
    for candidate in candidates:
        tool_call = _as_tool_call(candidate)
        if tool_call is not None:
            return tool_call
    return None


def _find_json_objects(text: str) -> list[dict]:
    """Return a list of JSON objects found in *text*."""
    # Try extracting from code fences first
    fence_pattern = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
    candidates: list[dict] = []
    for match in fence_pattern.finditer(text):
        try:
            obj = json.loads(match.group(1).strip())
            if isinstance(obj, dict):
                candidates.append(obj)
        except json.JSONDecodeError:
            continue

    # Try the whole text
    stripped = text.strip()
    if stripped:
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                candidates.append(obj)
        except json.JSONDecodeError:
            pass

    # Try to find a JSON object substring via brace matching
    brace_idx = stripped.find("{")
    if brace_idx >= 0:
        depth = 0
        for i in range(brace_idx, len(stripped)):
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
            if depth == 0:
                break
        if depth == 0:
            try:
                obj = json.loads(stripped[brace_idx : i + 1])
                if isinstance(obj, dict) and obj not in candidates:
                    candidates.append(obj)
            except (json.JSONDecodeError, ValueError):
                pass

    return candidates


def _as_tool_call(obj: dict) -> dict | None:
    """Return a normalised tool-call dict if *obj* looks like one, else None."""
    if "name" not in obj:
        return None
    args = obj.get("arguments", {})
    if not isinstance(args, dict):
        args = {}
    return {"name": obj["name"], "arguments": args}


def compute_exact_match(predicted: dict, reference: dict) -> bool:
    """Return True if *predicted* matches *reference* on name AND all args.

    This is a char-for-char comparison of the serialised tool calls:
    both tool name and every argument field must be identical.
    """
    if predicted.get("name") != reference.get("name"):
        return False
    return predicted.get("arguments", {}) == reference.get("arguments", {})


def compute_tool_name_accuracy(predicted_name: str, reference_name: str) -> float:
    """Return 1.0 if tool names match exactly, 0.0 otherwise (case-sensitive)."""
    return 1.0 if predicted_name == reference_name else 0.0


def compute_field_accuracy(predicted_args: dict, reference_args: dict) -> float:
    """Return the proportion of reference argument fields that match.

    Only fields present in the reference are considered.  Extra fields in
    the prediction are ignored (the model may generate additional context).
    """
    if not reference_args:
        return 1.0
    matches = sum(
        1 for key, val in reference_args.items()
        if key in predicted_args and predicted_args[key] == val
    )
    return matches / len(reference_args)


# ── Dataset integrity (dedup + reproducible splitting + label masking) ───

def extract_tool_call(messages: list[dict]) -> dict | None:
    """Extract the expected tool call from an assistant message.

    Returns a normalised dict with ``name`` and ``arguments`` keys, or
    ``None`` if no tool call is present. Handles both the generator's
    ``{"type": "function", "function": {"name", "arguments": "<json string>"}}``
    shape and pre-parsed dict arguments.
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


def load_jsonl(path: str) -> list[dict]:
    """Load a JSONL dataset file into a list of dict rows."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def canonical_tool_call_key(example: dict) -> tuple[str, str | None, str]:
    """Return a canonical dedup key for a dataset example.

    The key is ``(user_prompt, tool_name, canonical_arguments)`` where
    ``canonical_arguments`` is the argument dict re-serialized with sorted
    keys, so semantically identical tool calls produce the same key even if
    the dict key order differs.
    """
    messages = example.get("messages") or []
    user_prompt = ""
    tool_name: str | None = None
    arguments: Any = None
    for msg in messages:
        if msg.get("role") == "user" and msg.get("content"):
            user_prompt = str(msg["content"]).strip()
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            tcs = msg["tool_calls"]
            if tcs:
                func = tcs[0].get("function", tcs[0])
                tool_name = func.get("name")
                raw = func.get("arguments", {})
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        raw = {}
                arguments = raw
    canon_args = json.dumps(
        arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return (user_prompt, tool_name, canon_args)


def deduplicate_examples(examples: list[dict]) -> tuple[list[dict], dict]:
    """Drop examples with duplicate canonical keys; keep the first occurrence.

    Returns ``(unique_examples, stats)`` where ``stats`` reports how many
    duplicates were removed — this is what prevents train/test leakage when
    the same ``(prompt, tool, arguments)`` row would otherwise land in both
    the training and the test split.
    """
    seen: dict[tuple[str, str | None, str], dict] = {}
    duplicates = 0
    for example in examples:
        key = canonical_tool_call_key(example)
        if key in seen:
            duplicates += 1
        else:
            seen[key] = example
    unique = list(seen.values())
    stats = {
        "total_before_dedup": len(examples),
        "unique_after_dedup": len(unique),
        "duplicate_count": duplicates,
    }
    return unique, stats


def split_examples(
    examples: list[dict], seed: int, holdout_ratio: float = 0.2
) -> tuple[dict[str, list[dict]], dict]:
    """Split examples into train/val/test (80/10/10) reproducibly.

    The split replicates the historical train.py partition (80% train, then
    the 20% holdout split 50/50 into val and test) but operates on the
    deduplicated examples. The same seed always produces the same partition.

    Returns ``(splits, metadata)`` where metadata reports the split seed,
    split sizes, the train/test overlap count, and whether leakage was
    detected. After deduplication the overlap is expected to be zero.
    """
    rng = random.Random(seed)
    shuffled = list(examples)
    rng.shuffle(shuffled)

    n = len(shuffled)
    n_holdout = int(round(n * holdout_ratio))
    holdout = shuffled[:n_holdout]
    train = shuffled[n_holdout:]
    n_test = int(round(n_holdout / 2))
    test = holdout[:n_test]
    val = holdout[n_test:]

    train_keys = {canonical_tool_call_key(ex) for ex in train}
    test_keys = {canonical_tool_call_key(ex) for ex in test}
    overlap_count = len(train_keys & test_keys)

    splits = {"train": train, "val": val, "test": test}
    metadata = {
        "split_seed": seed,
        "train_size": len(train),
        "val_size": len(val),
        "test_size": len(test),
        "train_test_overlap_count": overlap_count,
        "leakage_detected": overlap_count > 0,
    }
    return splits, metadata


def build_splits(
    train_file: str, seed: int, holdout_ratio: float = 0.2
) -> tuple[dict[str, list[dict]], dict]:
    """Load a JSONL dataset, deduplicate, and split reproducibly.

    Returns ``(splits, metadata)``. This is the single code path used by both
    ``train.py`` and ``eval.py`` so the test partition is always identical.
    """
    examples = load_jsonl(train_file)

    unique, dedup_stats = deduplicate_examples(examples)
    splits, split_meta = split_examples(unique, seed, holdout_ratio)

    metadata = {
        "dataset_size": len(examples),
        **dedup_stats,
        **split_meta,
    }
    return splits, metadata


def build_completion_labels(
    token_ids: list[int],
    marker_token_ids: list[int],
    pad_token_id: int | None = None,
    ignore_index: int = -100,
) -> list[int]:
    """Build labels that train ONLY on the assistant/tool-call response.

    Tokens before the first ``marker_token_ids`` occurrence (the
    ``<|im_start|>assistant`` marker) get ``ignore_index`` (-100) so the model
    never learns from system/user tokens. Trailing padding tokens also get
    ``ignore_index``. If the marker is not found, every label is masked.

    This is the pure, unit-testable equivalent of TRL's
    ``DataCollatorForCompletionOnlyLM`` used by ``train.py``.
    """
    labels = [ignore_index] * len(token_ids)
    if not marker_token_ids:
        return labels

    start = _find_subsequence(token_ids, marker_token_ids)
    if start is None:
        return labels

    for i in range(start, len(token_ids)):
        labels[i] = token_ids[i]

    if pad_token_id is not None:
        # Mask only the trailing run of pad tokens (the padding region).
        i = len(token_ids) - 1
        while i >= 0 and token_ids[i] == pad_token_id:
            labels[i] = ignore_index
            i -= 1

    return labels


def _find_subsequence(seq: list[int], sub: list[int]) -> int | None:
    """Return the index of the first occurrence of *sub* in *seq*, or None."""
    m = len(sub)
    if m == 0 or m > len(seq):
        return None
    for i in range(len(seq) - m + 1):
        if seq[i : i + m] == sub:
            return i
    return None
