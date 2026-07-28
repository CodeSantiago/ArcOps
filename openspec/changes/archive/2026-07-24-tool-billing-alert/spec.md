# Spec: tool-billing-alert

## Added: get_billing_alert Tool Schema

### Purpose

Define the JSON Schema for `get_billing_alert` — querying AWS Cost Explorer for cost and usage data. Completes the 3-tool CloudOps function-calling set with sensible defaults so NL queries like "consultar gastos del mes" produce valid output with empty arguments.

### R1: Schema Structure

The schema MUST be a Draft 2020-12 `object` with `additionalProperties: false`.

**Scenario: Meta-schema valid**
- GIVEN the `get_billing_alert.json` schema file
- WHEN validated against the Draft 2020-12 meta-schema
- THEN validation MUST succeed

### R2: All Parameters Optional

All parameters SHOULD be optional. When called with empty arguments, the system MUST produce valid output by applying defaults.

| Field | Type | Default | Constraint |
|-------|------|---------|------------|
| `time_period_start` | string | First day of current month | Pattern: `\d{4}-\d{2}-\d{2}` |
| `time_period_end` | string | Today | Pattern: `\d{4}-\d{2}-\d{2}` |
| `granularity` | string | `MONTHLY` | Enum: `DAILY`, `MONTHLY`, `HOURLY` |
| `metrics` | array[string] | `["BlendedCost"]` | Enum items: `BlendedCost`, `UnblendedCost`, `UsageQuantity`, `AmortizedCost`, `NetUnblendedCost` |
| `group_by_service` | boolean | `false` | — |

**Scenario: Empty payload succeeds**
- GIVEN the `get_billing_alert` schema
- WHEN payload is `{}`
- THEN validation MUST succeed

**Scenario: All fields explicit**
- GIVEN the `get_billing_alert` schema
- WHEN payload specifies all fields with valid values
- THEN validation MUST succeed

**Scenario: Invalid date format**
- GIVEN the `get_billing_alert` schema
- WHEN `time_period_start` is `"2024/01/01"`
- THEN validation MUST fail on pattern mismatch

**Scenario: Invalid granularity enum**
- GIVEN the `get_billing_alert` schema
- WHEN `granularity` is `"YEARLY"`
- THEN validation MUST fail on enum mismatch

**Scenario: Invalid metrics enum item**
- GIVEN the `get_billing_alert` schema
- WHEN `metrics` includes `"TotalCost"`
- THEN validation MUST fail on enum mismatch

**Scenario: Wrong type for group_by_service**
- GIVEN the `get_billing_alert` schema
- WHEN `group_by_service` is string `"true"`
- THEN validation MUST fail on type mismatch

**Scenario: Extra unknown field**
- GIVEN the `get_billing_alert` schema
- WHEN payload includes `"extra":"value"`
- THEN validation MUST fail

**Scenario: Global service — no region**
- GIVEN the `get_billing_alert` schema
- WHEN checked for a `region` property
- THEN `region` MUST NOT be present in `properties`
- AND any payload including `"region":"us-east-1"` MUST fail (additionalProperties: false)

### R3: OpenAI Function-Calling Envelope

The tool entry in `tool_definitions.json` MUST follow the same `{name, description, parameters}` format as existing tools, with a factual NL description scoped to billing queries.

**Scenario: Description reflects billing domain**
- GIVEN the auto-generated entry for `get_billing_alert` in `tool_definitions.json`
- WHEN the `description` field is read
- THEN it MUST describe AWS Cost Explorer billing/cost querying
- AND it MUST NOT reference execution, boto3, or AWS API internals

## Modified: tool-definitions Aggregate

### R2: Completeness (MODIFIED)

The file MUST contain exactly 3 entries: `create_ec2_instance`, `restart_database`, and `get_billing_alert`.

(Previously: exactly 2 entries: create_ec2_instance and restart_database)

**Scenario (S4, updated): No extra tools**

| # | Scenario | GIVEN | WHEN | THEN |
|---|----------|-------|------|------|
| S4 | No extra tools | `tool_definitions.json` | Listed by `name` | Exactly `create_ec2_instance`, `restart_database`, and `get_billing_alert` present |

(Previously: Only create_ec2_instance and restart_database present)

## Generation

`tool_definitions.json` auto-discovers the new schema — zero script changes. Run `uv run python scripts/generate_tool_definitions.py` to regenerate. See `openspec/specs/tool-definitions/spec.md` for full generation process.
