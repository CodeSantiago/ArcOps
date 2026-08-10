"""Tests for dataset integrity: dedup, reproducible splits, label masking.

These cover the train/test leakage fixes:

- Examples are deduplicated by canonical ``(prompt, tool, arguments)`` key
  before splitting, so identical rows cannot land in both train and test.
- Splits are reproducible from a seed and report overlap/leakage metadata.
- ``build_completion_labels`` masks labels to the assistant/tool-call
  response only (-100 for system/user/padding tokens).
"""

from __future__ import annotations

import json

from scripts.training.pipeline_utils import (
    build_completion_labels,
    build_splits,
    canonical_tool_call_key,
    deduplicate_examples,
    split_examples,
)

# <|im_start|>assistant marker as fake token ids (deterministic for tests)
MARKER = [1, 2, 3]


def _example(prompt: str, tool: str, args: dict) -> dict:
    return {
        "messages": [
            {"role": "system", "content": "Sys."},
            {"role": "user", "content": prompt},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": tool,
                            "arguments": json.dumps(args, sort_keys=True),
                        },
                    }
                ],
            },
        ]
    }


def _write_jsonl(path, examples) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")


class TestCanonicalKey:
    """canonical_tool_call_key MUST ignore argument dict key order."""

    def test_semantically_equal_examples_share_key(self) -> None:
        a = _example("Create server", "create_ec2_instance",
                     {"region": "us-east-1", "instance_type": "t3.micro"})
        b = _example("Create server", "create_ec2_instance",
                     {"instance_type": "t3.micro", "region": "us-east-1"})
        assert canonical_tool_call_key(a) == canonical_tool_call_key(b)

    def test_different_prompt_different_key(self) -> None:
        a = _example("Create server", "create_ec2_instance", {"region": "us-east-1"})
        b = _example("Launch server", "create_ec2_instance", {"region": "us-east-1"})
        assert canonical_tool_call_key(a) != canonical_tool_call_key(b)


class TestDeduplicate:
    """deduplicate_examples MUST remove exact duplicates and report counts."""

    def test_duplicates_removed(self) -> None:
        ex = _example("Create server", "create_ec2_instance",
                      {"region": "us-east-1", "instance_type": "t3.micro"})
        unique, stats = deduplicate_examples([ex, dict(ex), dict(ex)])
        assert len(unique) == 1
        assert stats["total_before_dedup"] == 3
        assert stats["unique_after_dedup"] == 1
        assert stats["duplicate_count"] == 2

    def test_unique_examples_untouched(self) -> None:
        a = _example("Create server", "create_ec2_instance", {"region": "us-east-1"})
        b = _example("Restart db", "restart_database", {"region": "us-east-1"})
        unique, stats = deduplicate_examples([a, b])
        assert len(unique) == 2
        assert stats["duplicate_count"] == 0


class TestSplit:
    """split_examples MUST be seeded, 80/10/10, and report leakage."""

    def test_split_sizes(self) -> None:
        examples = [
            _example(f"p{i}", "create_ec2_instance", {"region": "us-east-1"})
            for i in range(100)
        ]
        splits, meta = split_examples(examples, seed=42)
        assert meta["train_size"] == 80
        assert meta["val_size"] == 10
        assert meta["test_size"] == 10
        assert len(splits["train"]) == 80
        assert len(splits["val"]) == 10
        assert len(splits["test"]) == 10

    def test_reproducible_with_same_seed(self) -> None:
        examples = [
            _example(f"p{i}", "create_ec2_instance", {"region": "us-east-1"})
            for i in range(50)
        ]
        s1, _ = split_examples(examples, seed=7)
        s2, _ = split_examples(examples, seed=7)
        assert [e["messages"][1]["content"] for e in s1["test"]] == [
            e["messages"][1]["content"] for e in s2["test"]
        ]

    def test_no_leakage_after_dedup(self) -> None:
        examples = [
            _example(f"p{i}", "create_ec2_instance", {"region": "us-east-1"})
            for i in range(50)
        ]
        unique, _ = deduplicate_examples(examples)
        splits, meta = split_examples(unique, seed=42)
        assert meta["train_test_overlap_count"] == 0
        assert meta["leakage_detected"] is False
        assert meta["split_seed"] == 42


class TestBuildSplits:
    """build_splits MUST read JSONL, dedupe, split, and report metadata."""

    def test_full_pipeline_metadata(self, tmp_path) -> None:
        examples = [
            _example(f"prompt {i}", "create_ec2_instance",
                     {"region": "us-east-1", "instance_type": "t3.micro"})
            for i in range(20)
        ]
        # add one exact duplicate
        examples.append(dict(examples[0]))
        path = tmp_path / "data.jsonl"
        _write_jsonl(path, examples)

        splits, meta = build_splits(str(path), seed=42)
        assert meta["dataset_size"] == 21
        assert meta["unique_after_dedup"] == 20
        assert meta["duplicate_count"] == 1
        assert meta["train_test_overlap_count"] == 0
        assert meta["leakage_detected"] is False
        assert meta["split_seed"] == 42
        assert meta["train_size"] + meta["val_size"] + meta["test_size"] == 20


class TestBuildCompletionLabels:
    """build_completion_labels MUST mask everything except the response.

    This is the focused unit test for training-label masking: system and
    user tokens are -100, the assistant response is trainable, and padding
    is -100.
    """

    def test_masks_system_and_user_tokens(self) -> None:
        tokens = [10, 11, 12, 13, 14, 1, 2, 3, 20, 21]
        labels = build_completion_labels(tokens, MARKER)
        assert labels[:5] == [-100] * 5  # system + user masked
        assert labels[5:] == tokens[5:]  # marker + response trainable

    def test_padding_masked(self) -> None:
        tokens = [10, 11, 1, 2, 3, 20, 99, 99, 99]  # 99 = pad
        labels = build_completion_labels(tokens, MARKER, pad_token_id=99)
        assert labels[5] == 20  # response token kept
        assert labels[6:] == [-100, -100, -100]  # trailing pad masked

    def test_marker_not_found_masks_everything(self) -> None:
        tokens = [10, 11, 12, 13, 14]
        labels = build_completion_labels(tokens, [7, 8, 9])
        assert labels == [-100] * 5

    def test_empty_marker_masks_everything(self) -> None:
        tokens = [10, 11, 12]
        labels = build_completion_labels(tokens, [])
        assert labels == [-100] * 3

    def test_no_pad_token_keeps_response(self) -> None:
        tokens = [10, 11, 1, 2, 3, 20, 21]
        labels = build_completion_labels(tokens, MARKER, pad_token_id=None)
        assert labels == [-100, -100, 1, 2, 3, 20, 21]
