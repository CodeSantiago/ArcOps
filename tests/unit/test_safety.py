"""Tests for the canonical safety layer (cloudops_fc.safety).

Covers the requirements that every ArcOps entry point (CLI, API, MCP, exec,
TUI) relies on: unknown parameters and missing required fields are rejected,
unknown tools are blocked, and cost/policy checks run without ML deps.
"""

from __future__ import annotations

from cloudops_fc.safety import (
    TOOL_SCHEMAS,
    SafetyResult,
    apply_policies,
    check,
    estimate_cost,
    validate_schema,
)


class TestSchemaValidation:
    """validate_schema MUST reject unknown params and missing requireds."""

    def test_valid_ec2_passes(self) -> None:
        result = validate_schema(
            "create_ec2_instance", {"region": "us-east-1", "instance_type": "t3.micro"}
        )
        assert result.passed is True
        assert result.blocked is False
        assert result.errors == []

    def test_unknown_parameter_blocked(self) -> None:
        result = validate_schema(
            "create_ec2_instance",
            {"region": "us-east-1", "instance_type": "t3.micro", "log_event": True},
        )
        assert result.blocked is True
        assert result.passed is False
        assert any("log_event" in e for e in result.errors)

    def test_missing_required_blocked(self) -> None:
        result = validate_schema("restart_database", {"region": "us-east-1"})
        assert result.blocked is True
        assert any("db_instance_identifier" in e for e in result.errors)

    def test_unknown_tool_blocked(self) -> None:
        result = validate_schema("delete_all_data", {})
        assert result.blocked is True
        assert any("Unknown tool" in e for e in result.errors)

    def test_billing_empty_payload_allowed(self) -> None:
        result = validate_schema("get_billing_alert", {})
        assert result.passed is True
        assert result.blocked is False


class TestCostEstimation:
    """estimate_cost MUST attach a monthly estimate for EC2."""

    def test_ec2_cost_estimated(self) -> None:
        result = estimate_cost(
            "create_ec2_instance", {"instance_type": "t3.micro", "min_count": 1}
        )
        assert result.estimated_cost > 0

    def test_billing_is_read_only(self) -> None:
        result = estimate_cost("get_billing_alert", {})
        assert result.estimated_cost == 0.0


class TestPolicies:
    """apply_policies MUST flag disruptive tools in production."""

    def test_restart_requires_approval_in_prod(self) -> None:
        result = apply_policies(
            "restart_database",
            {"db_instance_identifier": "prod", "region": "us-east-1"},
            env="production",
        )
        assert result.requires_approval is True

    def test_restart_in_dev_no_approval(self) -> None:
        result = apply_policies(
            "restart_database",
            {"db_instance_identifier": "dev", "region": "us-east-1"},
            env="development",
        )
        assert result.requires_approval is False


class TestCombinedCheck:
    """check MUST combine all checks and serialize cleanly."""

    def test_check_blocks_hallucinated_param(self) -> None:
        result = check(
            "create_ec2_instance",
            {"region": "us-east-1", "instance_type": "t3.micro", "send_email": True},
        )
        assert result.blocked is True
        data = result.to_dict()
        assert data["blocked"] is True
        assert data["passed"] is False
        assert data["errors"]

    def test_check_allows_valid_ec2_with_cost(self) -> None:
        result = check(
            "create_ec2_instance", {"region": "us-east-1", "instance_type": "t3.micro"}
        )
        assert result.passed is True
        assert result.blocked is False
        assert result.estimated_cost > 0

    def test_check_missing_required_is_blocked(self) -> None:
        result = check("restart_database", {"region": "us-east-1"})
        assert result.blocked is True
        assert not result.to_dict()["passed"]


class TestSchemasExposed:
    """TOOL_SCHEMAS MUST expose the three supported tools."""

    def test_tool_schemas_cover_all_tools(self) -> None:
        assert set(TOOL_SCHEMAS) == {
            "create_ec2_instance",
            "restart_database",
            "get_billing_alert",
        }

    def test_safety_result_defaults(self) -> None:
        r = SafetyResult()
        assert r.passed is True
        assert r.blocked is False
        assert r.requires_approval is False
        assert r.errors == []
        assert r.warnings == []
