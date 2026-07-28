"""Tests for schema validation — TDD RED phase targets stubs."""

from __future__ import annotations

import json
from importlib import resources

import jsonschema
import pytest


class TestMetaConformance:
    """R1: Every JSON schema MUST validate against Draft 2020-12 meta-schema."""

    SCHEMA_NAMES = ["create_ec2_instance", "get_billing_alert", "restart_database"]

    @pytest.mark.parametrize("name", SCHEMA_NAMES)
    def test_schema_passes_meta_validation(self, name: str) -> None:
        """Given a well-formed schema file, validate against meta-schema."""
        path = resources.files("cloudops_fc.schemas").joinpath(f"{name}.json")
        schema = json.loads(path.read_text("utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        # If no exception raised, meta-schema validated successfully

    def test_meta_schema_rejects_invalid_schema(self) -> None:
        """Given an invalid schema, meta-validation MUST fail."""
        bad_schema = {"type": "nonexistent"}
        with pytest.raises(jsonschema.SchemaError, match="nonexistent"):
            jsonschema.Draft202012Validator.check_schema(bad_schema)


class TestSchemaAccessibility:
    """R4: Schemas MUST be readable via importlib.resources."""

    SCHEMA_NAMES = ["create_ec2_instance", "get_billing_alert", "restart_database"]

    @pytest.mark.parametrize("name", SCHEMA_NAMES)
    def test_schema_loads_via_importlib(self, name: str) -> None:
        """Given the installed package, load schema JSON via importlib."""
        path = resources.files("cloudops_fc.schemas").joinpath(f"{name}.json")
        raw = path.read_text("utf-8")
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)
        assert "$schema" in parsed
        assert parsed.get("title") is not None

    def test_load_ec2_schema_title(self) -> None:
        """EC2 schema has the expected title."""
        path = resources.files("cloudops_fc.schemas").joinpath("create_ec2_instance.json")
        parsed = json.loads(path.read_text("utf-8"))
        assert parsed.get("title") == "Create EC2 Instance"

    def test_load_rds_schema_title(self) -> None:
        """RDS schema has the expected title."""
        path = resources.files("cloudops_fc.schemas").joinpath("restart_database.json")
        parsed = json.loads(path.read_text("utf-8"))
        assert parsed.get("title") == "Restart Database"

    def test_load_billing_schema_title(self) -> None:
        """Billing schema has the expected title."""
        path = resources.files("cloudops_fc.schemas").joinpath("get_billing_alert.json")
        parsed = json.loads(path.read_text("utf-8"))
        assert parsed.get("title") == "Get Billing Alert"


class TestValidPayload:
    """R2: A payload matching all schema constraints SHALL pass validation."""

    def test_valid_payload_passes(self, load_schema, validate_payload, valid_payload) -> None:
        """Given the create_ec2_instance schema, a valid payload passes."""
        schema = load_schema("create_ec2_instance")
        errors = validate_payload(schema, valid_payload)
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_valid_ec2_required_only(self, load_schema, validate_payload) -> None:
        """S1: EC2 schema accepts payload with only required fields."""
        schema = load_schema("create_ec2_instance")
        payload = {"region": "us-east-1", "instance_type": "t3.xlarge"}
        errors = validate_payload(schema, payload)
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_valid_ec2_security_group_rules(self, load_schema, validate_payload) -> None:
        """S8: EC2 schema accepts payload with valid security_group_rules."""
        schema = load_schema("create_ec2_instance")
        payload = {
            "region": "us-east-1",
            "instance_type": "t3.micro",
            "security_group_rules": [
                {"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
        }
        errors = validate_payload(schema, payload)
        assert errors == [], f"Expected no errors, got: {errors}"


class TestValidPayloadRDS:
    """R2: Valid restart_database payloads MUST pass validation."""

    def test_required_only(self, load_schema, validate_payload) -> None:
        """S1: RDS schema accepts payload with only required fields."""
        schema = load_schema("restart_database")
        payload = {"db_instance_identifier": "prod-primary", "region": "us-west-2"}
        errors = validate_payload(schema, payload)
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_with_failover(self, load_schema, validate_payload) -> None:
        """S2: RDS schema accepts payload with force_failover=True."""
        schema = load_schema("restart_database")
        payload = {
            "db_instance_identifier": "prod-primary",
            "region": "us-west-2",
            "force_failover": True,
        }
        errors = validate_payload(schema, payload)
        assert errors == [], f"Expected no errors, got: {errors}"


class TestValidPayloadBilling:
    """R2: Valid get_billing_alert payloads MUST pass validation."""

    def test_empty_payload_succeeds(self, load_schema, validate_payload) -> None:
        """S1: Empty payload {} MUST succeed (all params optional)."""
        schema = load_schema("get_billing_alert")
        errors = validate_payload(schema, {})
        assert errors == [], f"Expected no errors for empty payload, got: {errors}"

    def test_all_fields_explicit(
        self, load_schema, validate_payload, valid_billing_payload
    ) -> None:
        """S2: Full-parameter payload MUST pass validation."""
        schema = load_schema("get_billing_alert")
        errors = validate_payload(schema, valid_billing_payload)
        assert errors == [], f"Expected no errors, got: {errors}"


class TestMalformedPayloads:
    """R3: Malformed payloads MUST be rejected with clear errors."""

    SCHEMA_NAMES = ["create_ec2_instance", "get_billing_alert", "restart_database"]

    @pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
    def test_missing_required_field(
        self, load_schema, validate_payload, schema_name: str
    ) -> None:
        """Given a payload missing a required field, validation MUST fail."""
        schema = load_schema(schema_name)
        payload: dict
        missing: str | None
        if schema_name == "create_ec2_instance":
            payload = {"instance_type": "t3.micro"}  # missing region
            missing = "region"
        elif schema_name == "restart_database":
            payload = {"region": "us-east-1"}  # missing db_instance_identifier
            missing = "db_instance_identifier"
        else:
            # get_billing_alert has no required fields — empty payload is valid
            payload = {}
            missing = None
        errors = validate_payload(schema, payload)
        if missing is None:
            assert errors == [], (
                f"Expected no errors for empty billing payload, got: {errors}"
            )
        else:
            assert len(errors) > 0
            assert any(missing in e for e in errors), (
                f"Expected error mentioning '{missing}', got: {errors}"
            )

    @pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
    def test_wrong_value_type(
        self, load_schema, validate_payload, schema_name: str
    ) -> None:
        """Given a field with the wrong type, validation MUST fail."""
        schema = load_schema(schema_name)
        if schema_name == "create_ec2_instance":
            payload = {
                "region": "us-east-1",
                "instance_type": "t3.micro",
                "min_count": "one",
            }
        elif schema_name == "restart_database":
            payload = {
                "db_instance_identifier": "prod-primary",
                "region": "us-east-1",
                "force_failover": "yes",
            }
        else:
            payload = {
                "time_period_start": "2026-01-01",
                "group_by_service": "true",
            }
        errors = validate_payload(schema, payload)
        assert len(errors) > 0

    @pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
    def test_extra_unknown_field(
        self, load_schema, validate_payload, schema_name: str
    ) -> None:
        """Given an extra unknown field, additionalProperties=false rejects it."""
        schema = load_schema(schema_name)
        if schema_name == "create_ec2_instance":
            payload = {"region": "us-east-1", "instance_type": "t3.micro", "foo": "bar"}
        elif schema_name == "restart_database":
            payload = {
                "db_instance_identifier": "prod-primary",
                "region": "us-east-1",
                "foo": "bar",
            }
        else:
            payload = {
                "time_period_start": "2026-01-01",
                "time_period_end": "2026-07-24",
                "foo": "bar",
            }
        errors = validate_payload(schema, payload)
        assert len(errors) > 0
        assert any("foo" in e or "Additional properties" in e for e in errors)

    @pytest.mark.parametrize("schema_name", ["create_ec2_instance"])
    def test_invalid_instance_type_pattern(
        self, load_schema, validate_payload, schema_name: str
    ) -> None:
        """S4: Invalid instance_type pattern MUST be rejected."""
        schema = load_schema(schema_name)
        payload = {"region": "us-east-1", "instance_type": "invalid"}
        errors = validate_payload(schema, payload)
        assert len(errors) > 0

    @pytest.mark.parametrize("schema_name", ["create_ec2_instance"])
    def test_invalid_region_enum(
        self, load_schema, validate_payload, schema_name: str
    ) -> None:
        """S5: Invalid region enum value MUST be rejected."""
        schema = load_schema(schema_name)
        payload = {"region": "mars-1", "instance_type": "t3.micro"}
        errors = validate_payload(schema, payload)
        assert len(errors) > 0
        assert any("mars-1" in e or "enum" in e.lower() for e in errors)

    @pytest.mark.parametrize("schema_name", ["restart_database"])
    def test_invalid_identifier_pattern(
        self, load_schema, validate_payload, schema_name: str
    ) -> None:
        """S4 (RDS): Invalid db_instance_identifier pattern MUST be rejected."""
        schema = load_schema(schema_name)
        payload = {"db_instance_identifier": "Invalid_Name!", "region": "us-east-1"}
        errors = validate_payload(schema, payload)
        assert len(errors) > 0


    # --- Billing-specific malformed payload tests ---

    def test_billing_invalid_date_format(self, load_schema, validate_payload) -> None:
        """R2: Invalid date format '2024/01/01' MUST fail pattern mismatch."""
        schema = load_schema("get_billing_alert")
        payload = {"time_period_start": "2024/01/01"}
        errors = validate_payload(schema, payload)
        assert len(errors) > 0

    def test_billing_invalid_granularity_enum(self, load_schema, validate_payload) -> None:
        """R2: Invalid granularity 'YEARLY' MUST fail enum mismatch."""
        schema = load_schema("get_billing_alert")
        payload = {"granularity": "YEARLY"}
        errors = validate_payload(schema, payload)
        assert len(errors) > 0

    def test_billing_invalid_metrics_enum_item(self, load_schema, validate_payload) -> None:
        """R2: Invalid metrics item 'TotalCost' MUST fail enum mismatch."""
        schema = load_schema("get_billing_alert")
        payload = {"metrics": ["TotalCost"]}
        errors = validate_payload(schema, payload)
        assert len(errors) > 0

    def test_billing_region_rejected(self, load_schema, validate_payload) -> None:
        """R2: region field MUST be rejected (additionalProperties: false)."""
        schema = load_schema("get_billing_alert")
        payload = {"region": "us-east-1"}
        errors = validate_payload(schema, payload)
        assert len(errors) > 0
        assert any("region" in e or "Additional properties" in e for e in errors)


class TestToolDefinitions:
    """R1-R4: tool_definitions.json follows OpenAI function-calling format."""

    @pytest.fixture
    def tool_defs(self) -> list[dict]:
        """Load tool_definitions.json via importlib.resources."""
        path = resources.files("cloudops_fc.schemas").joinpath("tool_definitions.json")
        return json.loads(path.read_text("utf-8"))

    def test_valid_structure(self, tool_defs: list[dict]) -> None:
        """S1: Must be an array with entries having name/description/parameters."""
        assert isinstance(tool_defs, list)
        assert len(tool_defs) >= 2
        for entry in tool_defs:
            assert "name" in entry, f"Entry missing 'name': {entry}"
            assert isinstance(entry["name"], str)
            assert "description" in entry, f"Entry missing 'description': {entry}"
            assert isinstance(entry["description"], str)
            assert "parameters" in entry, f"Entry missing 'parameters': {entry}"
            params = entry["parameters"]
            assert params.get("type") == "object"
            assert "properties" in params

    def test_matches_ec2_source(
        self, tool_defs: list[dict], load_schema
    ) -> None:
        """S2: EC2 entry parameters are equivalent to the source schema."""
        source = load_schema("create_ec2_instance")
        entry = next(t for t in tool_defs if t["name"] == "create_ec2_instance")
        self._assert_parameters_equivalent(entry["parameters"], source)

    def test_matches_rds_source(
        self, tool_defs: list[dict], load_schema
    ) -> None:
        """S3: RDS entry parameters are equivalent to the source schema."""
        source = load_schema("restart_database")
        entry = next(t for t in tool_defs if t["name"] == "restart_database")
        self._assert_parameters_equivalent(entry["parameters"], source)

    def test_matches_billing_source(
        self, tool_defs: list[dict], load_schema
    ) -> None:
        """S4: Billing entry parameters are equivalent to the source schema."""
        source = load_schema("get_billing_alert")
        entry = next(t for t in tool_defs if t["name"] == "get_billing_alert")
        self._assert_parameters_equivalent(entry["parameters"], source)

    def test_no_extra_tools(self, tool_defs: list[dict]) -> None:
        """S4: Exactly the three expected tools are present."""
        names = sorted(t["name"] for t in tool_defs)
        assert names == [
            "create_ec2_instance",
            "get_billing_alert",
            "restart_database",
        ]

    def test_billing_description(self, tool_defs: list[dict]) -> None:
        """R3: get_billing_alert description references billing/cost, not boto3."""
        entry = next(t for t in tool_defs if t["name"] == "get_billing_alert")
        desc = entry["description"].lower()
        assert any(kw in desc for kw in ["cost", "billing", "usage"]), (
            f"Description should reference billing/cost, got: {entry['description']}"
        )
        assert "boto3" not in desc, (
            f"Description must not reference execution internals, got: {entry['description']}"
        )

    @staticmethod
    def _assert_parameters_equivalent(params: dict, source: dict) -> None:
        """Assert that the parameters block matches the source schema."""
        for key in ("type", "properties", "required", "additionalProperties"):
            assert params.get(key) == source.get(key), (
                f"Mismatch in '{key}': {params.get(key)} != {source.get(key)}"
            )


class TestPackageImportability:
    """R5: Package MUST be importable after uv sync."""

    def test_cloudops_fc_importable(self) -> None:
        """Given installed package, import cloudops_fc succeeds."""
        import cloudops_fc  # noqa: F401
