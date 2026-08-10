"""Template-family detection and family / unseen-value holdout splits.

Pure Python (no torch/transformers), fully unit-testable.

The ArcOps dataset generator (``scripts/generate_dataset_v3.py``) builds every
prompt from a fixed set of template families (e.g. ``ec2_basic`` =
``"Create a {size} server in {region}"``). A random train/test split can leak
an entire template phrasing into both sides, so a generalization measurement
must hold out COMPLETE families. This module provides:

- ``detect_template_family`` — which generator template produced a prompt
  (deterministic, regex-based; no model inference).
- ``split_examples_by_template_family`` — partition a dataset so complete
  families are held out for test and training uses the remaining families.
- ``split_examples_by_unseen_values`` — strict variant where specific
  region / instance_type / db / port values appear ONLY in test.
- ``validate_challenge_set`` — structural checks for the manual challenge set
  (``data/challenge_set.jsonl``).

Both holdout splitters operate on the deduplicated dataset (same canonical-key
dedup as the standard split), so no row can appear on both sides of any split.
"""

from __future__ import annotations

import json
import random
import re
from typing import Any

from scripts.training.pipeline_utils import deduplicate_examples, extract_tool_call

# ── Template family registry ────────────────────────────────────────────
# Ordered list of (family_name, regex patterns). A prompt belongs to the first
# family whose pattern fully matches it. Patterns mirror the exact literal
# templates in scripts/generate_dataset_v3.py, so a prompt maps to the family
# that actually generated it. Ordering rule: noise variants (trailing
# ", <noise>") and multi-port variants before the generic families they derive
# from.

# The generator's fixed noise phrase lists (see scripts/generate_dataset_v3.py).
_NOISE_EC2_PHRASES = (
    "also make sure it's secure",
    "and notify me when it's done",
    "please log everything",
    "and send an alert to the team",
    "ASAP, this is urgent",
    "thanks!",
    "and add monitoring",
    "make sure to enable backups",
    "remember to tag it properly",
)
_NOISE_RDS_PHRASES = (
    "but first check if it's healthy",
    "and let me know when it's back up",
    "but also log the event",
    "and notify the on-call engineer",
    "make sure to snapshot first",
    "please confirm before executing",
)


def _noise_alternation(phrases: tuple[str, ...]) -> str:
    return "|".join(re.escape(phrase) for phrase in phrases)


FAMILY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    # Noise variants carry a trailing ", <noise phrase>" from the fixed lists.
    (
        "noise_ec2",
        (
            rf"^Create a [a-z0-9.-]+ server in [a-z0-9-]+, "
            rf"(?:{_noise_alternation(_NOISE_EC2_PHRASES)})$",
            rf"^Launch a [a-z0-9.-]+ in [a-z0-9-]+ with port \d+ open, "
            rf"(?:{_noise_alternation(_NOISE_EC2_PHRASES)})$",
        ),
    ),
    (
        "noise_rds",
        (
            rf"^Restart [a-z0-9-]+ in [a-z0-9-]+, (?:{_noise_alternation(_NOISE_RDS_PHRASES)})$",
            rf"^Restart [a-z0-9-]+ in [a-z0-9-]+ with failover, "
            rf"(?:{_noise_alternation(_NOISE_RDS_PHRASES)})$",
        ),
    ),
    # EC2 families (multi-port / full combos before single-feature families).
    (
        "sg_multi",
        (
            r"^Create a [a-z0-9.-]+ server in [a-z0-9-]+ with ports \d+ and \d+ open$",
            r"^Launch a [a-z0-9.-]+ instance in [a-z0-9-]+ opening ports \d+, \d+$",
            r"^Deploy a [a-z0-9.-]+ EC2 in [a-z0-9-]+ with port \d+ and port \d+ accessible$",
        ),
    ),
    (
        "ec2_full",
        (
            r"^Create a [a-z0-9.-]+ server in [a-z0-9-]+ with port \d+ and tags "
            r"[A-Za-z]+=[A-Za-z0-9-]+(?: [A-Za-z]+=[A-Za-z0-9-]+)?$",
        ),
    ),
    (
        "ec2_tags",
        (
            r"^Create a [a-z0-9.-]+ server in [a-z0-9-]+ with tags "
            r"[A-Za-z]+=[A-Za-z0-9-]+(?: [A-Za-z]+=[A-Za-z0-9-]+)?$",
        ),
    ),
    (
        "sg_single",
        (
            r"^Create a [a-z0-9.-]+ server in [a-z0-9-]+ allowing port \d+$",
            r"^Launch a [a-z0-9.-]+ instance in [a-z0-9-]+ with port \d+ accessible$",
            r"^Deploy a [a-z0-9.-]+ EC2 in [a-z0-9-]+ and open port \d+$",
            r"^I need a [a-z0-9.-]+ server in [a-z0-9-]+ with port \d+ open$",
        ),
    ),
    (
        "ec2_ports",
        (
            r"^Create a (?:[a-z-]+ )?[a-z0-9.-]+ server in [a-z0-9-]+ with port \d+ open$",
            r"^Launch a [a-z0-9.-]+ in [a-z0-9-]+ and open port \d+$",
            r"^Deploy a [a-z0-9.-]+ server in [a-z0-9-]+, port \d+ accessible$",
        ),
    ),
    (
        "ec2_basic",
        (
            r"^Create a (?:[a-z-]+ )?[a-z0-9.-]+ server in [a-z0-9-]+$",
            r"^Launch a (?:[a-z-]+ )?[a-z0-9.-]+ EC2 instance in [a-z0-9-]+$",
            r"^Spin up a [a-z0-9.-]+ server in [a-z0-9-]+$",
            r"^I need a [a-z0-9.-]+ instance in [a-z0-9-]+$",
            r"^Provision a [a-z0-9.-]+ EC2 in [a-z0-9-]+$",
        ),
    ),
    # RDS families (failover phrasings before the plain restart family).
    (
        "rds_failover",
        (
            r"^Restart [a-z0-9-]+ in [a-z0-9-]+ with failover$",
            r"^Restart the [a-z0-9-]+ database and force a failover in [a-z0-9-]+$",
            r"^Reboot [a-z0-9-]+ in [a-z0-9-]+, enable force failover$",
            r"^Restart [a-z0-9-]+ in [a-z0-9-]+ without failover$",
            r"^Restart [a-z0-9-]+ in [a-z0-9-]+ no failover$",
            r"^Reboot [a-z0-9-]+ in [a-z0-9-]+ normally, no failover needed$",
        ),
    ),
    (
        "rds_basic",
        (
            r"^Restart the [a-z0-9-]+ database in [a-z0-9-]+$",
            r"^Reboot database [a-z0-9-]+ in [a-z0-9-]+$",
            r"^Restart [a-z0-9-]+ in [a-z0-9-]+$",
            r"^The [a-z0-9-]+ database is down, restart it in [a-z0-9-]+$",
        ),
    ),
    # Billing families.
    (
        "billing_metrics",
        (
            r"^What is our "
            r"(?:BlendedCost|UnblendedCost|UsageQuantity|AmortizedCost|NetUnblendedCost) "
            r"this month\?$",
            r"^Get the "
            r"(?:BlendedCost|UnblendedCost|UsageQuantity|AmortizedCost|NetUnblendedCost) "
            r"for this billing period$",
            r"^Show me AWS "
            r"(?:BlendedCost|UnblendedCost|UsageQuantity|AmortizedCost|NetUnblendedCost) "
            r"this month$",
            r"^Show me [\w ,.]+(?: and )?for this month$",
            r"^I need .+ broken down for this period$",
            r"^Give me the AWS .+ for this billing cycle$",
        ),
    ),
    (
        "billing_service",
        (
            r"^What did we spend on [A-Za-z0-9]+ this month\?$",
            r"^How much is [A-Za-z0-9]+ costing us on AWS\?$",
            r"^Show me the AWS costs for [A-Za-z0-9]+$",
            r"^Get the [A-Za-z0-9]+ billing from AWS$",
        ),
    ),
    (
        "billing_basic",
        (
            r"^How much did we spend on AWS this month\?$",
            r"^What are our AWS costs for this month\?$",
            r"^Show me the AWS billing for the current month$",
            r"^Get our AWS spending for this month$",
            r"^Check AWS costs for the current billing period$",
            r"^What did we spend on AWS this month\?$",
            r"^How much is our AWS bill\?$",
        ),
    ),
    ("billing_daily", (r"^Show me daily AWS costs from \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}$",)),
    (
        "granularity_daily",
        (
            r"^Show daily costs from \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}$",
            r"^I need a day-by-day breakdown from \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}$",
            r"^Give me the daily AWS spend between \d{4}-\d{2}-\d{2} and \d{4}-\d{2}-\d{2}$",
        ),
    ),
]

KNOWN_FAMILIES: tuple[str, ...] = tuple(name for name, _ in FAMILY_PATTERNS)

_COMPILED: list[tuple[str, list[re.Pattern[str]]]] | None = None


def _compiled_patterns() -> list[tuple[str, list[re.Pattern[str]]]]:
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = [
            (name, [re.compile(pattern) for pattern in patterns])
            for name, patterns in FAMILY_PATTERNS
        ]
    return _COMPILED


def user_prompt(example: dict) -> str:
    """Return the stripped user prompt of a ChatML example ('' if absent)."""
    for msg in example.get("messages") or []:
        if msg.get("role") == "user" and msg.get("content"):
            return str(msg["content"]).strip()
    return ""


def detect_template_family(prompt: str) -> str | None:
    """Return the generator template family that produced *prompt*.

    Deterministic regex match against the exact templates in
    ``scripts/generate_dataset_v3.py``. Returns ``None`` for prompts that do
    not come from any generator template (e.g. the manual challenge set).
    """
    prompt = prompt.strip()
    for family, patterns in _compiled_patterns():
        for pattern in patterns:
            if pattern.fullmatch(prompt):
                return family
    return None


def family_counts(examples: list[dict]) -> tuple[dict[str, int], int]:
    """Count examples per template family.

    Returns ``(counts, unknown_count)`` where unknown examples did not match
    any generator template.
    """
    counts: dict[str, int] = {}
    unknown = 0
    for example in examples:
        family = detect_template_family(user_prompt(example))
        if family is None:
            unknown += 1
        else:
            counts[family] = counts.get(family, 0) + 1
    return counts, unknown


# ── Unseen-value holdout ────────────────────────────────────────────────

# Friendly CLI names -> argument field names. "port" resolves inside
# ``security_group_rules`` list items; "db" is the RDS identifier field.
ARG_FIELD_ALIASES: dict[str, str] = {
    "db": "db_instance_identifier",
    "port": "port",
}
UNSEEN_FIELDS: tuple[str, ...] = ("region", "instance_type", "db_instance_identifier", "port")


def normalize_field(field: str) -> str:
    """Map a friendly field name (``db``, ``port``) to its argument key."""
    return ARG_FIELD_ALIASES.get(field, field)


def extract_arg_values(args: dict, field: str) -> set[str]:
    """Return the set of string values for *field* in a tool-call argument dict.

    Handles direct values (``region``, ``instance_type``,
    ``db_instance_identifier``) and values nested inside list items
    (``security_group_rules[].port``). All values are normalized to strings so
    an int port (80) compares equal to the CLI value "80".
    """
    values: set[str] = set()

    def _add(value: Any) -> None:
        if isinstance(value, (dict, list)):
            return
        values.add(str(value))

    if field in args:
        value = args[field]
        if isinstance(value, list):
            for item in value:
                _add(item)
        else:
            _add(value)
    # Nested scan: field inside dict items of any list-valued argument.
    for value in args.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and field in item:
                    _add(item[field])
    return values


def parse_unseen_values(items: list[str]) -> dict[str, set[str]]:
    """Parse ``--unseen`` CLI items (``FIELD=value1,value2``) into a dict.

    Raises ``ValueError`` for unknown fields or empty value lists.
    """
    unseen: dict[str, set[str]] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(
                f"Invalid --unseen value {item!r}: expected FIELD=value1,value2 "
                f"(fields: {', '.join(UNSEEN_FIELDS)})"
            )
        field, values = item.split("=", 1)
        field = normalize_field(field.strip())
        if field not in UNSEEN_FIELDS:
            raise ValueError(
                f"Unknown unseen field {field!r}; use one of {', '.join(UNSEEN_FIELDS)}"
            )
        parsed = {value.strip() for value in values.split(",") if value.strip()}
        if not parsed:
            raise ValueError(f"--unseen {item!r} has no values")
        unseen[field] = parsed
    return unseen


# ── Holdout splits ──────────────────────────────────────────────────────


def split_examples_by_template_family(
    examples: list[dict],
    test_families: list[str] | tuple[str, ...] | set[str],
    seed: int = 42,
    val_ratio: float = 0.1,
) -> tuple[dict[str, list[dict]], dict]:
    """Split examples so COMPLETE template families are held out for test.

    All examples whose detected family is in *test_families* go to ``test``;
    the remaining families are split into ``train``/``val`` with a seeded
    shuffle. Deduplication (canonical key) runs first, so no duplicate row can
    straddle the partition.

    Args:
        examples: Dataset rows (ChatML messages).
        test_families: Family names to hold out entirely for test.
        seed: RNG seed for the train/val carve (NOT the family selection).
        val_ratio: Fraction of the train-family pool used for validation.

    Returns:
        ``(splits, metadata)`` — splits has ``train``/``val``/``test`` keys;
        metadata reports family counts, the family partition, split sizes,
        dedup stats, and whether any test-family example leaked into train/val.
    """
    unknown_families = sorted(set(test_families) - set(KNOWN_FAMILIES))
    if unknown_families:
        raise ValueError(
            f"Unknown template families: {unknown_families}. "
            f"Known families: {', '.join(KNOWN_FAMILIES)}"
        )

    unique, dedup_stats = deduplicate_examples(examples)
    test_family_set = set(test_families)

    grouped: dict[str, list[dict]] = {}
    unknown: list[dict] = []
    for example in unique:
        family = detect_template_family(user_prompt(example))
        if family is None:
            unknown.append(example)
        else:
            grouped.setdefault(family, []).append(example)

    test_pool = [example for family in test_family_set for example in grouped.get(family, [])]
    train_pool = [
        example
        for family, family_examples in grouped.items()
        if family not in test_family_set
        for example in family_examples
    ]

    rng = random.Random(seed)
    shuffled = list(train_pool)
    rng.shuffle(shuffled)
    n_val = int(round(len(shuffled) * val_ratio))
    val = shuffled[:n_val]
    train = shuffled[n_val:]

    # Leakage check: no example from a held-out family may appear in train/val.
    train_val_families = {detect_template_family(user_prompt(ex)) for ex in train + val}
    leakage = len(train_val_families & test_family_set) > 0

    counts, unknown_count = family_counts(unique)
    metadata: dict[str, Any] = {
        "mode": "template_family",
        "test_families": sorted(test_family_set),
        "train_families": sorted(set(grouped) - test_family_set),
        "family_counts": counts,
        "unknown_count": unknown_count,
        "train_size": len(train),
        "val_size": len(val),
        "test_size": len(test_pool),
        "val_ratio": val_ratio,
        "split_seed": seed,
        "leakage_detected": leakage,
        "dataset_size": dedup_stats["total_before_dedup"],
        "unique_after_dedup": dedup_stats["unique_after_dedup"],
        "duplicate_count": dedup_stats["duplicate_count"],
    }
    return {"train": train, "val": val, "test": test_pool}, metadata


def split_examples_by_unseen_values(
    examples: list[dict],
    unseen_values: dict[str, set[str]],
    seed: int = 42,
    val_ratio: float = 0.1,
) -> tuple[dict[str, list[dict]], dict]:
    """Strict holdout: configured region/instance_type/db/port values in test only.

    Any example whose arguments contain a value in *unseen_values* for one of
    the configured fields goes to ``test``; everything else becomes the
    train-family pool (seeded ``train``/``val`` carve). The metadata reports
    ``unseen_value_violations`` — values found in train/val — which MUST be
    empty for the holdout to be strict.

    Args:
        examples: Dataset rows (ChatML messages).
        unseen_values: Field -> values mapping (fields normalized via
            ``normalize_field``; e.g. ``{"region": {"ca-central-1"}}`` or
            ``{"port": {"6379"}}``).
        seed: RNG seed for the train/val carve.
        val_ratio: Fraction of the non-test pool used for validation.

    Returns:
        ``(splits, metadata)`` with the same shape as the template splitter.
    """
    unseen = {normalize_field(field): set(values) for field, values in unseen_values.items()}
    for field in unseen:
        if field not in UNSEEN_FIELDS:
            raise ValueError(
                f"Unknown unseen field {field!r}; use one of {', '.join(UNSEEN_FIELDS)}"
            )

    unique, dedup_stats = deduplicate_examples(examples)

    def _arguments(example: dict) -> dict:
        tool_call = extract_tool_call(example.get("messages") or [])
        args = tool_call.get("arguments") if tool_call else None
        return args if isinstance(args, dict) else {}

    test_pool: list[dict] = []
    train_pool: list[dict] = []
    for example in unique:
        args = _arguments(example)
        if any(extract_arg_values(args, field) & values for field, values in unseen.items()):
            test_pool.append(example)
        else:
            train_pool.append(example)

    rng = random.Random(seed)
    shuffled = list(train_pool)
    rng.shuffle(shuffled)
    n_val = int(round(len(shuffled) * val_ratio))
    val = shuffled[:n_val]
    train = shuffled[n_val:]

    # Strict verification: an unseen value must never appear in train/val args.
    violations: dict[str, list[str]] = {}
    for field, values in unseen.items():
        found: set[str] = set()
        for example in train + val:
            found |= extract_arg_values(_arguments(example), field) & values
        if found:
            violations[field] = sorted(found)

    metadata: dict[str, Any] = {
        "mode": "unseen_values",
        "unseen_values": {field: sorted(values) for field, values in unseen.items()},
        "unseen_value_violations": violations,
        "train_size": len(train),
        "val_size": len(val),
        "test_size": len(test_pool),
        "val_ratio": val_ratio,
        "split_seed": seed,
        "dataset_size": dedup_stats["total_before_dedup"],
        "unique_after_dedup": dedup_stats["unique_after_dedup"],
        "duplicate_count": dedup_stats["duplicate_count"],
    }
    return {"train": train, "val": val, "test": test_pool}, metadata


def load_jsonl(path: str) -> list[dict]:
    """Load a JSONL dataset file into a list of dict rows."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def split_file_by_template_family(
    path: str,
    test_families: list[str] | tuple[str, ...] | set[str],
    seed: int = 42,
    val_ratio: float = 0.1,
) -> tuple[dict[str, list[dict]], dict]:
    """File-level wrapper for ``split_examples_by_template_family``."""
    return split_examples_by_template_family(load_jsonl(path), test_families, seed, val_ratio)


def split_file_by_unseen_values(
    path: str,
    unseen_values: dict[str, set[str]],
    seed: int = 42,
    val_ratio: float = 0.1,
) -> tuple[dict[str, list[dict]], dict]:
    """File-level wrapper for ``split_examples_by_unseen_values``."""
    return split_examples_by_unseen_values(load_jsonl(path), unseen_values, seed, val_ratio)


# ── Challenge set validation ────────────────────────────────────────────

KNOWN_TOOLS: tuple[str, ...] = (
    "create_ec2_instance",
    "restart_database",
    "get_billing_alert",
)


def validate_challenge_set(examples: list[dict]) -> list[str]:
    """Validate ChatML/tool-call structure of challenge-set rows.

    Returns a list of error messages (empty when the set is valid). Checks:
    exactly one system/user/assistant message triplet, a parseable tool call
    in the assistant message, a known tool name, JSON-parseable arguments, a
    non-empty user prompt, and no duplicate prompts.
    """
    errors: list[str] = []
    seen_prompts: set[str] = set()
    for index, example in enumerate(examples):
        prefix = f"row {index}"
        messages = example.get("messages")
        if not isinstance(messages, list) or len(messages) != 3:
            errors.append(f"{prefix}: expected exactly 3 messages, got {messages!r}")
            continue
        roles = [m.get("role") for m in messages]
        if roles != ["system", "user", "assistant"]:
            errors.append(f"{prefix}: unexpected roles {roles}")
        prompt = messages[1].get("content") if len(messages) > 1 else None
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append(f"{prefix}: user prompt is empty")
        elif prompt in seen_prompts:
            errors.append(f"{prefix}: duplicate user prompt")
        seen_prompts.add(prompt)

        assistant = messages[2] if len(messages) > 2 else {}
        tool_calls = assistant.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            errors.append(f"{prefix}: assistant message has no tool_calls")
            continue
        first = tool_calls[0]
        function = first.get("function") if isinstance(first, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if name not in KNOWN_TOOLS:
            errors.append(f"{prefix}: unknown tool name {name!r}")
        raw_args = function.get("arguments") if isinstance(function, dict) else None
        try:
            parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            if not isinstance(parsed, dict):
                errors.append(f"{prefix}: arguments do not parse to an object")
        except (json.JSONDecodeError, TypeError):
            errors.append(f"{prefix}: arguments are not valid JSON: {raw_args!r}")
    return errors
