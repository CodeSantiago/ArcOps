# Project Scaffolding — Specification

## Purpose

Bootstrap the `fine_tuning_model` repository: uv-managed Python 3.12, src-layout package `cloudops_fc` with JSON schema-validation capability, quality toolchain (pytest, ruff, mypy), git foundation, and updated SDD config.

---

## Requirements

### R1: Schema Meta-Conformance

Every JSON schema file under `src/cloudops_fc/schemas/` MUST validate against the JSON Schema Draft 2020-12 meta-schema.

#### Scenario: Meta-schema passes for valid schema
- GIVEN a well-formed schema file `create_ec2_instance.json`
- WHEN validated against the Draft 2020-12 meta-schema
- THEN the result MUST indicate success

#### Scenario: Meta-schema rejects invalid schema
- GIVEN a schema with an invalid `type` value (e.g., `"type": "nonexistent"`)
- WHEN validated against the meta-schema
- THEN validation MUST fail with a descriptive error

### R2: Valid Payload Acceptance

A payload matching all schema constraints SHALL pass validation. This MUST hold for both `create_ec2_instance` and `restart_database` schemas.

#### Scenario: create_ec2_instance valid payload (Unchanged)
- GIVEN the `create_ec2_instance` schema
- WHEN a valid payload is validated
- THEN result MUST indicate success

#### Scenario: restart_database valid payload (Added)
- GIVEN the `restart_database` schema
- WHEN a valid payload is validated
- THEN result MUST indicate success

### R3: Malformed Payload Rejection

An invalid payload MUST be rejected with a clear error message. This MUST hold for both schemas.

#### Scenario: Missing required field (Parametrized)
- GIVEN either `create_ec2_instance` or `restart_database` schema
- WHEN any required field is omitted
- THEN validation MUST fail, naming the missing field

#### Scenario: Wrong value type (Parametrized)
- GIVEN either schema with a typed field
- WHEN the field has the wrong type (string for integer)
- THEN validation MUST fail, type-mismatch error

#### Scenario: Extra unknown field (Parametrized)
- GIVEN either schema with `additionalProperties: false`
- WHEN payload includes an unrecognized field
- THEN validation MUST fail

### R4: Schema Accessibility

Schemas MUST be readable at runtime via `importlib.resources` with no CWD assumptions.

#### Scenario: Load schema via importlib
- GIVEN the installed `cloudops_fc` package
- WHEN `importlib.resources.files("cloudops_fc.schemas").joinpath("create_ec2_instance.json").read_text()` executes
- THEN the full schema JSON MUST be returned

### R5: Package Importability

The `cloudops_fc` package MUST be importable after `uv sync`.

#### Scenario: Import succeeds
- GIVEN an activated uv-managed environment
- WHEN `python -c "import cloudops_fc"` runs
- THEN exit code MUST be 0

### R6: Test Coverage

The test suite MUST achieve ≥80% line coverage.

#### Scenario: Coverage threshold met
- GIVEN an activated uv environment
- WHEN `pytest --cov=cloudops_fc --cov-report=term-missing` runs
- THEN total coverage MUST be ≥80%

### R7: Lint & Type Compliance

`ruff` and `mypy` MUST pass with zero errors.

#### Scenario: ruff passes
- GIVEN an activated uv environment
- WHEN `ruff check src/cloudops_fc/ tests/` runs
- THEN exit code MUST be 0

#### Scenario: mypy passes
- GIVEN an activated uv environment
- WHEN `mypy src/cloudops_fc/` runs
- THEN exit code MUST be 0

### R8: Git Bootstrap

The repository SHALL contain an initial commit with only scaffold files.

#### Scenario: Initial commit exists
- GIVEN `git init` and scaffold file creation
- WHEN `git log --oneline` is inspected
- THEN exactly one commit MUST exist with a descriptive conventional-commit message

### R9: SDD Config Update

`openspec/config.yaml` MUST reflect the new tooling state.

#### Scenario: Config values set
- GIVEN the updated `openspec/config.yaml`
- THEN `testing.runner` MUST be `pytest`
- AND `testing.quality.linter` MUST be `ruff`
- AND `testing.quality.type_checker` MUST be `mypy`
- AND `verify.coverage_threshold` MUST be `80`
- AND `strict_tdd` MUST be `true`
