"""Tests for schema validation — TDD RED phase targets stubs."""

from __future__ import annotations

import json
from importlib import resources

import jsonschema
import pytest


class TestMetaConformance:
    """R1: Every JSON schema MUST validate against Draft 2020-12 meta-schema."""

    SCHEMA_NAMES = ["create_ec2_instance"]

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

    def test_load_schema_via_importlib(self) -> None:
        """Given the installed package, load schema JSON via importlib."""
        path = resources.files("cloudops_fc.schemas").joinpath("create_ec2_instance.json")
        raw = path.read_text("utf-8")
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)
        assert parsed.get("title") == "Create EC2 Instance"
        assert "$schema" in parsed


class TestValidPayload:
    """R2: A payload matching all schema constraints SHALL pass validation."""

    def test_valid_payload_passes(self, load_schema, validate_payload, valid_payload):
        """Given the create_ec2_instance schema, a valid payload passes."""
        schema = load_schema("create_ec2_instance")
        errors = validate_payload(schema, valid_payload)
        assert errors == [], f"Expected no errors, got: {errors}"


class TestMalformedPayloads:
    """R3: Malformed payloads MUST be rejected with clear errors."""

    def test_missing_required_field(self, load_schema, validate_payload, valid_payload):
        """Given a payload missing 'ami_id', validation MUST fail."""
        schema = load_schema("create_ec2_instance")
        bad = dict(valid_payload)
        del bad["ami_id"]
        errors = validate_payload(schema, bad)
        assert len(errors) > 0
        assert any("ami_id" in e or "ami" in e.lower() for e in errors)

    def test_wrong_value_type(self, load_schema, validate_payload, valid_payload):
        """Given min_count as string instead of integer, validation fails."""
        schema = load_schema("create_ec2_instance")
        bad = dict(valid_payload)
        bad["min_count"] = "one"
        errors = validate_payload(schema, bad)
        assert len(errors) > 0

    def test_extra_unknown_field(self, load_schema, validate_payload, valid_payload):
        """Given an extra field 'foo', additionalProperties=false rejects it."""
        schema = load_schema("create_ec2_instance")
        bad = dict(valid_payload)
        bad["foo"] = "bar"
        errors = validate_payload(schema, bad)
        assert len(errors) > 0
        assert any("foo" in e or "Additional properties" in e for e in errors)


class TestPackageImportability:
    """R5: Package MUST be importable after uv sync."""

    def test_cloudops_fc_importable(self) -> None:
        """Given installed package, import cloudops_fc succeeds."""
        import cloudops_fc  # noqa: F401
