# Apply Summary — Tools Schema

**Change**: tools-schema
**Mode**: Strict TDD (via openspec/config.yaml)
**Date**: 2026-07-24

## Phase 1: Schema Files

- [x] 1.1 Replace `create_ec2_instance.json` — 5 fields → 11 fields with `region` enum (12 regions), `instance_type` regex, `security_group_rules` array, 5 more optional fields
- [x] 1.2 Create `restart_database.json` — required `db_instance_identifier` (pattern), `region` (enum), optional `force_failover`
- [x] Created `regions.json` — shared 12-region enum fragment

## Phase 2: Generation

- [x] 2.1 Create `scripts/generate_tool_definitions.py` — reads schemas/ dir, transforms to OpenAI function-calling format, writes `tool_definitions.json`
- [x] 2.2 Run generator → `tool_definitions.json` with 2 entries (create_ec2_instance, restart_database)

## Phase 3: Testing

- [x] 3.1 Update `conftest.py` — `valid_payload` fixture expanded for new EC2 schema; added `valid_restart_payload` and `regions` fixtures
- [x] 3.2 Parametrize `SCHEMA_NAMES` across `["create_ec2_instance", "restart_database"]` in both `TestMetaConformance` and `TestSchemaAccessibility`
- [x] 3.3 Add `TestValidPayloadRDS` class (2 scenarios) + parametrized `TestMalformedPayloads` across both schemas (missing field, wrong type, extra) + schema-specific pattern/enum tests
- [x] 3.4 Add `TestToolDefinitions` class — 4 scenarios (structure, EC2 match, RDS match, no extra tools)

## Results

- **Total tests**: 26 passing (was 8 before change)
- **Safety net baseline**: 8/8 preserved
- **All GREEN**: 26/26 passing in 0.19s

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | N/A (schema data) | N/A | ✅ 8/8 | ➖ Structural | ✅ Passed | ➖ Skip (data) | ✅ Clean |
| 1.2 | N/A (schema data) | N/A | ✅ 8/8 | ➖ Structural | ✅ Passed | ➖ Skip (data) | ✅ Clean |
| 2.1 | N/A (generator script) | N/A | ✅ 8/8 | ➖ Structural | ✅ Run OK | ➖ Skip (tool) | ✅ Clean |
| 2.2 | `test_tool_definitions` | Unit | N/A (gen) | ➖ Generated | ✅ 26/26 | ➖ Skip (gen) | ✅ Clean |
| 3.1 | `conftest.py` | N/A | ✅ 8/8 | ➖ Fixture | ✅ 26/26 | ➖ Skip (helper) | ✅ Clean |
| 3.2 | `test_schema_validation` | Unit | ✅ 8/8 | ✅ Written | ✅ 26/26 | ✅ 2 schemas | ✅ Clean |
| 3.3 | `test_schema_validation` | Unit | ✅ 8/8 | ✅ Written | ✅ 26/26 | ✅ 7 cases | ✅ Clean |
| 3.4 | `test_schema_validation` | Unit | ✅ 26/26 | ✅ Written | ✅ 26/26 | ✅ 4 cases | ✅ Clean |

## Deviations from Design

None — implementation matches design.

## Issues Found

None.

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `src/cloudops_fc/schemas/create_ec2_instance.json` | Modified | Replaced 5-field scaffold with 11-field schema: region enum, instance_type regex, 8 optional fields |
| `src/cloudops_fc/schemas/restart_database.json` | Created | New RDS schema: db_instance_identifier (pattern), region (enum), force_failover (optional bool) |
| `src/cloudops_fc/schemas/regions.json` | Created | Shared 12-region enum fragment for code/tests |
| `scripts/generate_tool_definitions.py` | Created | Reads schemas/ dir, transforms to OpenAI function-calling format, writes tool_definitions.json |
| `src/cloudops_fc/schemas/tool_definitions.json` | Created | Auto-generated OpenAI function-calling array with 2 entries |
| `tests/conftest.py` | Modified | Expanded valid_payload; added valid_restart_payload and regions fixtures |
| `tests/unit/test_schema_validation.py` | Modified | Parametrized meta-conformance (2 schemas); added TestValidPayloadRDS; parametrized TestMalformedPayloads; added TestToolDefinitions |

## Next Steps

Ready for `sdd-verify`.
