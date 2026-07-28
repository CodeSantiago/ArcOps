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
    """Return a well-formed EC2 instance payload (required + optional fields)."""
    return {
        "region": "us-east-1",
        "instance_type": "t3.micro",
        "ami_id": "ami-0c55b159cbfafe1f0",
        "min_count": 1,
        "max_count": 1,
        "key_name": "my-key",
        "security_group_rules": [
            {"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"},
        ],
        "subnet_id": "subnet-abc123",
        "associate_public_ip": True,
        "tags": [
            {"key": "Name", "value": "web-server"},
        ],
    }


@pytest.fixture(name="valid_restart_payload")
def fixture_valid_restart_payload() -> dict:
    """Return a well-formed RDS restart payload (required + optional fields)."""
    return {
        "db_instance_identifier": "prod-primary",
        "region": "us-west-2",
        "force_failover": True,
    }


@pytest.fixture(name="valid_billing_payload")
def fixture_valid_billing_payload() -> dict:
    """Return a well-formed billing payload with all fields explicit."""
    return {
        "time_period_start": "2026-01-01",
        "time_period_end": "2026-07-24",
        "granularity": "MONTHLY",
        "metrics": ["BlendedCost"],
        "group_by_service": False,
    }


@pytest.fixture(name="regions")
def fixture_regions() -> list[str]:
    """Return the shared list of supported AWS regions."""
    return [
        "us-east-1",
        "us-east-2",
        "us-west-1",
        "us-west-2",
        "eu-west-1",
        "eu-central-1",
        "eu-west-2",
        "ap-southeast-1",
        "ap-southeast-2",
        "ap-northeast-1",
        "sa-east-1",
        "ca-central-1",
    ]
