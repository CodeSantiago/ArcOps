# Tasks: get_billing_alert Tool Schema

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~150 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

## Phase 1: Schema & Generation

- [x] 1.1 Create `src/cloudops_fc/schemas/get_billing_alert.json` — Draft 2020-12 schema, all params optional, no `required` key, `additionalProperties: false`
- [x] 1.2 Run `uv run python scripts/generate_tool_definitions.py` — regenerates `tool_definitions.json` with 3 entries (auto-discovers new schema, zero script changes)

## Phase 2: Test Infrastructure

- [x] 2.1 Add `valid_billing_payload` fixture to `tests/conftest.py` — full-params payload with valid dates, `MONTHLY`, `["BlendedCost"]`, `group_by_service: false`
- [x] 2.2 Extend `SCHEMA_NAMES` in `TestMetaConformance` and `TestSchemaAccessibility` — add `"get_billing_alert"`
- [x] 2.3 Create `TestValidPayloadBilling` — tests for `{}` (all defaults), all fields explicit, plus edge cases matching R2 spec scenarios
- [x] 2.4 Extend `TestMalformedPayloads` `SCHEMA_NAMES` — add `"get_billing_alert"`; add billing-specific tests: invalid date format, bad granularity enum, bad metrics enum item, wrong type for `group_by_service`, extra field, `region` rejection
- [x] 2.5 Update `test_no_extra_tools` in `TestToolDefinitions` — expect sorted names `["create_ec2_instance", "get_billing_alert", "restart_database"]`
- [x] 2.6 Add billing description check in `TestToolDefinitions` — verify `description` field for `get_billing_alert` entry references cost/billing (no boto3/execution internals)

## Phase 3: Aggregate Spec Update

- [x] 3.1 Update `openspec/specs/tool-definitions/spec.md` R2 — "exactly 3 entries" and S4 updated tool list
