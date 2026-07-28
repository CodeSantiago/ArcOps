# Proposal: Tools Schema (Fase 1 — Function/Tool Definitions)

## Intent

Define two JSON Schema tool definitions (`create_ec2_instance`, `restart_database`) in OpenAI function-calling format for the fine-tuning pipeline. Replace the scaffolding seed with production-ready schemas. Enable Fase 2 dataset generation by producing training-ready function definitions.

## Scope

### In Scope

- Replace `create_ec2_instance.json` seed with expanded schema: required `region` (enum), `instance_type` (regex), optional fields (`ami_id`, `min_count`, `max_count`, `key_name`, `security_group_rules`, `subnet_id`, `associate_public_ip`, `tags`)
- Create `restart_database.json`: required `db_instance_identifier` (pattern) and `region` (enum), optional `force_failover`
- Generate `tool_definitions.json` in OpenAI functions-calling format for training pipeline consumption
- Extend `tests/conftest.py` with valid_payload fixtures for both tools
- Parametrize existing validation tests across 2 schemas

### Out of Scope

- `get_billing_alert` tool schema (deferred to next change)
- Dataset generation or training (Fase 2)
- Tool execution layer (Fase 3+)
- Tool registry or metadata wrappers

## Capabilities

### New Capabilities

- `tool-create-ec2-instance`: EC2 instance launch function schema with CloudOps abstraction (`security_group_rules`)
- `tool-restart-database`: RDS database restart function schema
- `tool-definitions`: Training-ready function definitions in OpenAI functions-calling format

### Modified Capabilities

- `schema-validation`: Extend R2/R3 scenarios to cover 2 schemas instead of 1

## Approach

Flat per-tool JSON Schema files (Approach 1 from exploration). Seed replaced in-place. `validate_payload()` unchanged — `load_schema("restart_database")` works automatically via `importlib.resources`. `tool_definitions.json` generated as a derived artifact from the source schemas.

`instance_type`: regex pattern `^[a-z][0-9][a-z]+\.[0-9]+[a-z]+$` (not enum). `region`: curated 12-region enum. `security_group_rules` kept as CloudOps abstraction (model learns port/protocol/cidr; downstream translates to SG creation).

Output format: OpenAI function-calling style — `{"name": "...", "arguments": {...}}` with `role` and `tool_call_id` in conversation context.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/cloudops_fc/schemas/create_ec2_instance.json` | Modified | 5 → 11 fields, added constraints |
| `src/cloudops_fc/schemas/restart_database.json` | New | RDS reboot schema (3 fields) |
| `src/cloudops_fc/schemas/tool_definitions.json` | New | OpenAI functions-calling format derived from schemas |
| `tests/conftest.py` | Modified | Valid_payload fixtures for both tools |
| `tests/unit/test_schema_validation.py` | Modified | Parametrize across 2 schemas |
| `src/cloudops_fc/schemas/__init__.py` | None | No changes — importlib pattern covers new files |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| instance_type regex over-/under-matches | Med | Test against common families; prefer false-positives over false-negatives |
| region enum stale as AWS adds regions | Low | Document maintenance expectation; stable major-region set |
| security_group_rules abstraction confuses model | Low | Document translation gap in tool_definitions; no schema impact |
| Schema ↔ training definition drift | Med | `tool_definitions.json` is auto-generated from schemas — single source of truth |

## Rollback Plan

`git revert` the commit changing `create_ec2_instance.json` and adding `restart_database.json` + `tool_definitions.json`. All tests pass before merge — rollback is safe if any test fails.

## Dependencies

- Existing uv-managed Python 3.12 environment
- Existing `jsonschema` library

## Success Criteria

- [ ] All validation test cases pass across both schemas (existing + new)
- [ ] Meta-conformance passes for both schemas
- [ ] `tool_definitions.json` schema-conforms and matches source schemas
- [ ] ≥80% test coverage maintained
