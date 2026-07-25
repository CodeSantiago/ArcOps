"""Schema loading and validation utilities."""

from __future__ import annotations

import json
from importlib import resources


def load_schema(name: str) -> dict:
    """Load a JSON Schema by its stem name (e.g. 'create_ec2_instance').

    Returns the parsed schema dict.
    Raises FileNotFoundError if the schema does not exist as package data.
    """
    path = resources.files("cloudops_fc.schemas").joinpath(f"{name}.json")
    with path.open("rb") as f:
        return json.loads(f.read().decode("utf-8"))


def validate_payload(schema: dict, payload: dict) -> list[str]:
    """Validate a payload dict against a schema dict.

    Returns a list of error messages (empty list = valid).
    """
    import jsonschema

    errors: list[str] = []
    validator = jsonschema.Draft202012Validator(schema)
    for error in validator.iter_errors(payload):
        errors.append(error.message)
    return errors
