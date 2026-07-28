"""Tests for training pipeline utility functions (RED phase).

Tests pure functions from scripts/training/pipeline_utils.py:
- serialize_tool_calls: convert OpenAI tool_calls to assistant text content
"""

from __future__ import annotations

import json

import pytest

from scripts.training.pipeline_utils import serialize_tool_calls


class TestSerializeToolCalls:
    """serialize_tool_calls MUST convert tool_calls to text content."""

    def test_single_tool_call_parsed_to_content(self) -> None:
        """Given one tool_call, assistant content MUST contain the tool name."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Create an EC2 instance in us-east-2"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "create_ec2_instance",
                            "arguments": '{"region": "us-east-2"}',
                        },
                    }
                ],
            },
        ]
        result = serialize_tool_calls(messages)
        assert result[2]["role"] == "assistant"
        assert result[2]["content"] is not None
        assert "create_ec2_instance" in result[2]["content"]
        assert "us-east-2" in result[2]["content"]

    def test_single_tool_call_produces_valid_json(self) -> None:
        """The assistant content MUST be valid JSON with name and arguments keys."""
        messages = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "Query"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "restart_database",
                            "arguments": '{"db_instance_identifier": "prod-db"}',
                        },
                    }
                ],
            },
        ]
        result = serialize_tool_calls(messages)
        parsed = json.loads(result[2]["content"])
        assert parsed["name"] == "restart_database"
        assert parsed["arguments"]["db_instance_identifier"] == "prod-db"

    def test_preserves_system_and_user_messages(self) -> None:
        """System and user messages MUST remain unchanged."""
        messages = [
            {"role": "system", "content": "System prompt."},
            {"role": "user", "content": "User query."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"type": "function", "function": {"name": "test", "arguments": "{}"}}
                ],
            },
        ]
        result = serialize_tool_calls(messages)
        assert result[0] == {"role": "system", "content": "System prompt."}
        assert result[1] == {"role": "user", "content": "User query."}

    def test_no_tool_calls_unchanged(self) -> None:
        """Messages without assistant or without tool_calls MUST pass through."""
        messages = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "Hi."},
            {"role": "assistant", "content": "Hello!"},
        ]
        result = serialize_tool_calls(messages)
        assert result == messages

    def test_multiple_tool_calls(self) -> None:
        """Multiple tool_calls MUST be serialized as a JSON array."""
        messages = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "Do two things."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "create_ec2_instance",
                            "arguments": '{"region": "us-east-2"}',
                        },
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "get_billing_alert",
                            "arguments": '{"metrics": ["BlendedCost"]}',
                        },
                    },
                ],
            },
        ]
        result = serialize_tool_calls(messages)
        parsed = json.loads(result[2]["content"])
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "create_ec2_instance"
        assert parsed[1]["name"] == "get_billing_alert"

    def test_empty_tool_calls_list(self) -> None:
        """Empty tool_calls list MUST produce empty string content."""
        messages = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "Query."},
            {"role": "assistant", "content": None, "tool_calls": []},
        ]
        result = serialize_tool_calls(messages)
        assert result[2]["content"] == ""

    def test_arguments_string_parsed_to_dict(self) -> None:
        """The arguments string MUST be parsed from JSON string to object."""
        messages = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "Query."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "create_ec2_instance",
                            "arguments": '{"region": "us-east-2", "instance_type": "m5.large"}',
                        },
                    }
                ],
            },
        ]
        result = serialize_tool_calls(messages)
        parsed = json.loads(result[2]["content"])
        assert isinstance(parsed["arguments"], dict)
        assert parsed["arguments"]["region"] == "us-east-2"
        assert parsed["arguments"]["instance_type"] == "m5.large"
