"""Shared fixtures for the cloudops_fc test suite."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from cloudops_fc.schemas import load_schema, validate_payload


@pytest.fixture(name="load_schema")
def fixture_load_schema() -> Callable[[str], dict]:
    """Return the load_schema function for test use."""
    return load_schema


@pytest.fixture(name="validate_payload")
def fixture_validate_payload() -> Callable[[dict, dict], list[str]]:
    """Return the validate_payload function for test use."""
    return validate_payload


@pytest.fixture(name="valid_payload")
def fixture_valid_payload() -> dict:
    """Return a well-formed EC2 instance payload."""
    return {
        "instance_type": "t3.micro",
        "ami_id": "ami-0c55b159cbfafe1f0",
        "region": "us-east-1",
        "min_count": 1,
        "max_count": 1,
    }
