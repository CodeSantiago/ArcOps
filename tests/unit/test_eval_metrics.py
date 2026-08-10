"""Tests for evaluation metric functions (RED phase).

Tests pure functions from scripts/training/pipeline_utils.py:
- parse_tool_call: extract tool call dict from generated text
- compute_exact_match: char-for-char accuracy
- compute_tool_name_accuracy: tool name match
- compute_field_accuracy: argument field match ratio
"""

from __future__ import annotations

from scripts.training.pipeline_utils import (
    compute_exact_match,
    compute_field_accuracy,
    compute_tool_name_accuracy,
    parse_tool_call,
)


class TestParseToolCall:
    """parse_tool_call MUST extract tool call dict from generated text."""

    def test_plain_json_object(self) -> None:
        """Given plain JSON text, MUST return parsed dict."""
        text = '{"name": "create_ec2_instance", "arguments": {"region": "us-east-2"}}'
        result = parse_tool_call(text)
        assert result is not None
        assert result["name"] == "create_ec2_instance"
        assert result["arguments"]["region"] == "us-east-2"

    def test_json_in_code_fence(self) -> None:
        """Given JSON inside triple backticks, MUST extract and parse."""
        text = (
            'Here is the result:\n```json\n{"name": "restart_database", '
            '"arguments": {"db_instance_identifier": "prod-db"}}\n```'
        )
        result = parse_tool_call(text)
        assert result is not None
        assert result["name"] == "restart_database"

    def test_no_json_returns_none(self) -> None:
        """Given text without JSON, MUST return None."""
        text = "I don't know how to do that."
        result = parse_tool_call(text)
        assert result is None

    def test_malformed_json_returns_none(self) -> None:
        """Given malformed JSON, MUST return None."""
        text = '{"name": "create_ec2_instance", "arguments": {broken}}'
        result = parse_tool_call(text)
        assert result is None

    def test_json_with_surrounding_text(self) -> None:
        """Given JSON with surrounding text, MUST extract the JSON part."""
        text = (
            'Sure! Calling: {"name": "get_billing_alert", '
            '"arguments": {"metrics": ["BlendedCost"]}}'
        )
        result = parse_tool_call(text)
        assert result is not None
        assert result["name"] == "get_billing_alert"

    def test_missing_arguments_key(self) -> None:
        """Given JSON without 'arguments' key, MUST still return dict with empty args."""
        text = '{"name": "create_ec2_instance"}'
        result = parse_tool_call(text)
        assert result is not None
        assert result["name"] == "create_ec2_instance"
        assert result["arguments"] == {}


class TestComputeExactMatch:
    """compute_exact_match MUST compare tool name + all args perfectly."""

    def test_identical_tool_and_args(self) -> None:
        """Given identical tool name and arguments, MUST return True."""
        pred = {"name": "create_ec2_instance", "arguments": {"region": "us-east-2"}}
        ref = {"name": "create_ec2_instance", "arguments": {"region": "us-east-2"}}
        assert compute_exact_match(pred, ref) is True

    def test_different_tool_name(self) -> None:
        """Given different tool name, MUST return False."""
        pred = {"name": "create_ec2_instance", "arguments": {"region": "us-east-2"}}
        ref = {"name": "restart_database", "arguments": {"region": "us-east-2"}}
        assert compute_exact_match(pred, ref) is False

    def test_different_arguments(self) -> None:
        """Given same tool but different args, MUST return False."""
        pred = {"name": "create_ec2_instance", "arguments": {"region": "us-east-1"}}
        ref = {"name": "create_ec2_instance", "arguments": {"region": "us-east-2"}}
        assert compute_exact_match(pred, ref) is False

    def test_missing_argument_key(self) -> None:
        """Given pred missing a key the ref has, MUST return False."""
        pred = {"name": "create_ec2_instance", "arguments": {"region": "us-east-2"}}
        ref = {
            "name": "create_ec2_instance",
            "arguments": {"region": "us-east-2", "instance_type": "m5.large"},
        }
        assert compute_exact_match(pred, ref) is False

    def test_both_empty_args(self) -> None:
        """Given both have empty arguments and same name, MUST return True."""
        pred = {"name": "test", "arguments": {}}
        ref = {"name": "test", "arguments": {}}
        assert compute_exact_match(pred, ref) is True


class TestComputeToolNameAccuracy:
    """compute_tool_name_accuracy MUST return 1.0 for match, 0.0 for mismatch."""

    def test_matching_name(self) -> None:
        """Given matching tool names, MUST return 1.0."""
        assert compute_tool_name_accuracy("create_ec2_instance", "create_ec2_instance") == 1.0

    def test_different_name(self) -> None:
        """Given different tool names, MUST return 0.0."""
        assert compute_tool_name_accuracy("create_ec2_instance", "restart_database") == 0.0

    def test_case_sensitive(self) -> None:
        """Given case-different names, MUST return 0.0 (case-sensitive)."""
        assert compute_tool_name_accuracy("Create_EC2", "create_ec2") == 0.0

    def test_empty_names(self) -> None:
        """Given both empty strings, MUST return 1.0."""
        assert compute_tool_name_accuracy("", "") == 1.0


class TestComputeFieldAccuracy:
    """compute_field_accuracy MUST return proportion of matching fields."""

    def test_all_fields_match(self) -> None:
        """Given identical argument dicts, MUST return 1.0."""
        pred = {"region": "us-east-2", "instance_type": "m5.large"}
        ref = {"region": "us-east-2", "instance_type": "m5.large"}
        assert compute_field_accuracy(pred, ref) == 1.0

    def test_half_fields_match(self) -> None:
        """Given 1 of 2 fields match, MUST return 0.5."""
        pred = {"region": "us-east-2", "instance_type": "t2.micro"}
        ref = {"region": "us-east-2", "instance_type": "m5.large"}
        assert compute_field_accuracy(pred, ref) == 0.5

    def test_no_fields_match(self) -> None:
        """Given no matching fields, MUST return 0.0."""
        pred = {"region": "us-east-1"}
        ref = {"region": "us-east-2"}
        assert compute_field_accuracy(pred, ref) == 0.0

    def test_empty_pred_args(self) -> None:
        """Given empty predicted args, MUST return 0.0."""
        pred = {}
        ref = {"region": "us-east-2"}
        assert compute_field_accuracy(pred, ref) == 0.0

    def test_empty_ref_args(self) -> None:
        """Given empty reference args, MUST return 1.0 (nothing to match)."""
        pred = {"region": "us-east-2"}
        ref = {}
        assert compute_field_accuracy(pred, ref) == 1.0

    def test_extra_pred_fields_ignored(self) -> None:
        """Extra fields in prediction MUST NOT affect score."""
        pred = {"region": "us-east-2", "extra_field": "ignored"}
        ref = {"region": "us-east-2"}
        assert compute_field_accuracy(pred, ref) == 1.0

    def test_nested_dict_values(self) -> None:
        """Given nested dict values, MUST compare deeply."""
        pred = {"tags": [{"key": "Name", "value": "test"}]}
        ref = {"tags": [{"key": "Name", "value": "test"}]}
        assert compute_field_accuracy(pred, ref) == 1.0

    def test_nested_dict_mismatch(self) -> None:
        """Given mismatched nested values, MUST return 0.0 for that field."""
        pred = {"tags": [{"key": "Name", "value": "wrong"}]}
        ref = {"tags": [{"key": "Name", "value": "correct"}]}
        assert compute_field_accuracy(pred, ref) == 0.0
