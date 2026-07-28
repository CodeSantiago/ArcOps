# Tool Schema: restart_database

## Purpose

Define the JSON Schema for the `restart_database` function-calling tool — restarting RDS database instances with optional failover. Part of the CloudOps function-calling fine-tuning pipeline.

---

## Requirements

### R1: Schema Structure

The `restart_database` schema MUST be a Draft 2020-12 `object` with `additionalProperties: false`.

#### Scenario: Meta-schema passes
- GIVEN the `restart_database` schema file
- WHEN validated against the Draft 2020-12 meta-schema
- THEN validation MUST succeed

### R2: Required Fields

| Field | Type | Constraint |
|-------|------|------------|
| `db_instance_identifier` | string | Pattern: `^[a-z][a-z0-9-]+[a-z0-9]$` |
| `region` | string | Same 12-region enum as create_ec2_instance |

### R3: Optional Fields

| Field | Type | Default | Constraint |
|-------|------|---------|------------|
| `force_failover` | boolean | false | — |

---

## Scenarios

| # | Scenario | GIVEN | WHEN | THEN |
|---|----------|-------|------|------|
| S1 | Valid payload — required | `restart_database` schema | Payload: `{"db_instance_identifier":"prod-primary","region":"us-west-2"}` | Validation MUST succeed |
| S2 | Valid payload — with force_failover | Same schema | Payload includes `force_failover: true` | Validation MUST succeed |
| S3 | Missing required field | Same schema | Payload omits `db_instance_identifier` | Validation MUST fail, names missing field |
| S4 | Invalid identifier pattern | Same schema | `db_instance_identifier` is `"Invalid_Name!"` | Validation MUST fail, pattern mismatch |
| S5 | Extra unknown field | Same schema | Payload includes `"unexpected":"value"` | Validation MUST fail |

---

## Source Schema

File: `src/cloudops_fc/schemas/restart_database.json`
