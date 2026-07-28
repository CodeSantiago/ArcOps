"""Pure utility functions for the QLoRA training pipeline.

These functions have NO dependencies on torch, transformers, or other
heavy ML libraries — they are pure Python and easily unit-testable.
"""

from __future__ import annotations

import json
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
