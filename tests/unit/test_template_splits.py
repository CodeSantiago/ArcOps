"""Tests for template-family detection, holdout splits, and the challenge set.

Covers the evaluation-protocol additions (no model required):

- ``detect_template_family`` maps prompts to the generator template family
  that produced them (deterministic regex, no inference).
- ``split_examples_by_template_family`` holds out COMPLETE families for test.
- ``split_examples_by_unseen_values`` keeps configured values in test only.
- ``data/challenge_set.jsonl`` is structurally valid, non-duplicated, and not
  derived from any generator template.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.training.pipeline_utils import deduplicate_examples, extract_tool_call
from scripts.training.template_families import (
    KNOWN_FAMILIES,
    detect_template_family,
    extract_arg_values,
    family_counts,
    parse_unseen_values,
    split_examples_by_template_family,
    split_examples_by_unseen_values,
    user_prompt,
    validate_challenge_set,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHALLENGE_SET = PROJECT_ROOT / "data" / "challenge_set.jsonl"


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


# Representative prompts for every generator template family.
FAMILY_PROBES: dict[str, str] = {
    "ec2_basic": "Create a small t3.micro server in us-east-1",
    "ec2_ports": "Launch a t3.small in eu-west-1 and open port 80",
    "ec2_tags": "Create a t3.micro server in us-east-1 with tags Name=web",
    "ec2_full": "Create a t3.micro server in us-east-1 with port 80 and tags Name=web Env=prod",
    "sg_single": "Create a t3.micro server in us-east-1 allowing port 80",
    "sg_multi": "Create a t3.micro server in us-east-1 with ports 80 and 443 open",
    "rds_basic": "Restart prod-db-01 in us-east-1",
    "rds_failover": "Restart prod-db-01 in us-east-1 with failover",
    "billing_basic": "How much did we spend on AWS this month?",
    "billing_service": "Show me the AWS costs for EC2",
    "billing_daily": "Show me daily AWS costs from 2026-07-01 to 2026-07-14",
    "granularity_daily": "Show daily costs from 2026-07-01 to 2026-07-14",
    "billing_metrics": "Show me UnblendedCost and BlendedCost for this month",
    "noise_ec2": "Create a t3.micro server in us-east-1, also make sure it's secure",
    "noise_rds": "Restart prod-db-01 in us-east-1, but also log the event",
}


class TestDetectTemplateFamily:
    """detect_template_family MUST map generator prompts to their family."""

    @pytest.mark.parametrize("family", sorted(KNOWN_FAMILIES))
    def test_probe_maps_to_its_family(self, family: str) -> None:
        probe = FAMILY_PROBES[family]
        assert detect_template_family(probe) == family

    def test_unknown_prompt_returns_none(self) -> None:
        assert detect_template_family("What is the weather today?") is None

    def test_empty_prompt_returns_none(self) -> None:
        assert detect_template_family("") is None

    def test_noise_variants_not_confused_with_base_families(self) -> None:
        # The noise suffix ", <noise>" must NOT collapse into ec2_basic/rds_basic.
        assert (
            detect_template_family("Restart prod-db-01 in us-east-1, but also log the event")
            == "noise_rds"
        )
        assert (
            detect_template_family("Create a t3.micro server in us-east-1, please log everything")
            == "noise_ec2"
        )


class TestFamilyCounts:
    """family_counts MUST tally families and report unknowns."""

    def test_counts_and_unknown(self) -> None:
        examples = [
            _example(FAMILY_PROBES["ec2_basic"], "create_ec2_instance", {"region": "us-east-1"}),
            _example(FAMILY_PROBES["ec2_basic"], "create_ec2_instance", {"region": "us-east-2"}),
            _example(FAMILY_PROBES["rds_basic"], "restart_database", {"region": "us-east-1"}),
            _example("unrelated prompt", "get_billing_alert", {}),
        ]
        counts, unknown = family_counts(examples)
        assert counts["ec2_basic"] == 2
        assert counts["rds_basic"] == 1
        assert unknown == 1


class TestTemplateFamilySplit:
    """split_examples_by_template_family MUST hold out complete families."""

    def test_held_out_family_only_in_test(self) -> None:
        examples = []
        for region in ["us-east-1", "us-east-2", "eu-west-1"]:
            examples.append(
                _example(
                    FAMILY_PROBES["ec2_basic"].replace("us-east-1", region),
                    "create_ec2_instance",
                    {"instance_type": "t3.micro", "region": region},
                )
            )
        for region in ["us-east-1", "us-east-2"]:
            examples.append(
                _example(
                    FAMILY_PROBES["ec2_ports"].replace("us-east-1", region),
                    "create_ec2_instance",
                    {
                        "instance_type": "t3.small",
                        "region": region,
                        "security_group_rules": [
                            {"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"}
                        ],
                    },
                )
            )

        splits, metadata = split_examples_by_template_family(examples, ["ec2_ports"], seed=42)
        test_families = {detect_template_family(user_prompt(ex)) for ex in splits["test"]}
        assert test_families == {"ec2_ports"}
        assert len(splits["test"]) == 2
        # Held-out family must not leak into train/val.
        for split in ("train", "val"):
            for example in splits[split]:
                assert detect_template_family(user_prompt(example)) != "ec2_ports"
        assert metadata["test_families"] == ["ec2_ports"]
        assert metadata["leakage_detected"] is False
        assert metadata["train_size"] + metadata["val_size"] + metadata["test_size"] == 5

    def test_dedup_runs_before_split(self) -> None:
        example = _example(
            FAMILY_PROBES["ec2_basic"],
            "create_ec2_instance",
            {"instance_type": "t3.micro", "region": "us-east-1"},
        )
        examples = [dict(example), dict(example), dict(example)]
        splits, metadata = split_examples_by_template_family(examples, ["ec2_ports"], seed=42)
        assert metadata["duplicate_count"] == 2
        assert metadata["unique_after_dedup"] == 1
        assert len(splits["train"]) + len(splits["val"]) == 1

    def test_unknown_family_name_rejected(self) -> None:
        examples = [_example(FAMILY_PROBES["ec2_basic"], "create_ec2_instance", {})]
        with pytest.raises(ValueError, match="Unknown template families"):
            split_examples_by_template_family(examples, ["not_a_family"])


class TestUnseenValueSplit:
    """split_examples_by_unseen_values MUST keep configured values in test only."""

    def test_unseen_region_only_in_test(self) -> None:
        examples = [
            _example(
                "Create a t3.micro server in us-east-1",
                "create_ec2_instance",
                {"instance_type": "t3.micro", "region": "us-east-1"},
            ),
            _example(
                "Create a t3.micro server in us-east-2",
                "create_ec2_instance",
                {"instance_type": "t3.micro", "region": "us-east-2"},
            ),
            _example(
                "Create a t3.micro server in ca-central-1",
                "create_ec2_instance",
                {"instance_type": "t3.micro", "region": "ca-central-1"},
            ),
        ]
        splits, metadata = split_examples_by_unseen_values(
            examples, {"region": {"ca-central-1"}}, seed=42
        )
        assert len(splits["test"]) == 1
        assert user_prompt(splits["test"][0]).endswith("ca-central-1")
        assert metadata["test_size"] == 1
        assert metadata["unseen_value_violations"] == {}

    def test_unseen_port_extracted_from_nested_rules(self) -> None:
        sg = [{"port": 6379, "protocol": "tcp", "cidr": "0.0.0.0/0"}]
        examples = [
            _example(
                "Open port 6379",
                "create_ec2_instance",
                {"instance_type": "t3.micro", "region": "us-east-1", "security_group_rules": sg},
            ),
            _example(
                "Open port 80",
                "create_ec2_instance",
                {
                    "instance_type": "t3.micro",
                    "region": "us-east-1",
                    "security_group_rules": [{"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"}],
                },
            ),
        ]
        splits, metadata = split_examples_by_unseen_values(examples, {"port": {"6379"}}, seed=42)
        assert len(splits["test"]) == 1
        assert extract_arg_values(
            extract_tool_call(splits["test"][0]["messages"])["arguments"], "port"
        ) == {"6379"}
        assert metadata["unseen_value_violations"] == {}

    def test_db_alias_normalized(self) -> None:
        examples = [
            _example(
                "Restart payments-prod-2026",
                "restart_database",
                {"db_instance_identifier": "payments-prod-2026", "region": "us-east-1"},
            ),
            _example(
                "Restart users-db",
                "restart_database",
                {"db_instance_identifier": "users-db", "region": "us-east-1"},
            ),
        ]
        splits, _ = split_examples_by_unseen_values(
            examples, {"db": {"payments-prod-2026"}}, seed=42
        )
        assert len(splits["test"]) == 1
        assert (
            extract_tool_call(splits["test"][0]["messages"])["arguments"]["db_instance_identifier"]
            == "payments-prod-2026"
        )

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown unseen field"):
            split_examples_by_unseen_values([], {"bogus": {"x"}})


class TestParseUnseenValues:
    """parse_unseen_values MUST parse CLI-style FIELD=value1,value2 items."""

    def test_parses_fields_and_values(self) -> None:
        parsed = parse_unseen_values(["region=ca-central-1,ap-northeast-1", "port=6379"])
        assert parsed["region"] == {"ca-central-1", "ap-northeast-1"}
        assert parsed["port"] == {"6379"}

    def test_missing_equals_rejected(self) -> None:
        with pytest.raises(ValueError, match="expected FIELD=value1,value2"):
            parse_unseen_values(["region"])


class TestChallengeSetValidity:
    """data/challenge_set.jsonl MUST be structurally valid and non-template."""

    @pytest.fixture
    def challenge_rows(self) -> list[dict]:
        assert CHALLENGE_SET.is_file(), f"challenge set missing: {CHALLENGE_SET}"
        rows = []
        with open(CHALLENGE_SET, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def test_size_in_range(self, challenge_rows: list[dict]) -> None:
        assert 50 <= len(challenge_rows) <= 100

    def test_structure_valid(self, challenge_rows: list[dict]) -> None:
        errors = validate_challenge_set(challenge_rows)
        assert errors == []

    def test_prompts_not_derived_from_generator_templates(self, challenge_rows: list[dict]) -> None:
        for row in challenge_rows:
            prompt = user_prompt(row)
            assert detect_template_family(prompt) is None, (
                f"challenge prompt matches a generator template: {prompt!r}"
            )

    def test_all_tools_covered(self, challenge_rows: list[dict]) -> None:
        tools = {extract_tool_call(row["messages"])["name"] for row in challenge_rows}
        assert tools == {"create_ec2_instance", "restart_database", "get_billing_alert"}

    def test_prompts_unique(self, challenge_rows: list[dict]) -> None:
        prompts = {user_prompt(row) for row in challenge_rows}
        assert len(prompts) == len(challenge_rows)

    def test_rows_deduplicate_cleanly(self, challenge_rows: list[dict]) -> None:
        unique, stats = deduplicate_examples(challenge_rows)
        assert stats["duplicate_count"] == 0
        assert len(unique) == len(challenge_rows)
