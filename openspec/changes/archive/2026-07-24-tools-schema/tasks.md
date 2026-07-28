# Tasks: Tools Schema

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~330 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Schemas + generator + tests | Single PR | ~330 lines, under budget |

## Phase 1: Schema Files

- [x] 1.1 Replace `src/cloudops_fc/schemas/create_ec2_instance.json` — 5 fields → 11 fields with `region` enum, `instance_type` regex, `security_group_rules` array, 5 more optional fields
- [x] 1.2 Create `src/cloudops_fc/schemas/restart_database.json` — required `db_instance_identifier` (pattern), `region` (shared enum), optional `force_failover`

## Phase 2: Generation Script

- [x] 2.1 Create `scripts/generate_tool_definitions.py` — reads all `schemas/*.json`, transforms to OpenAI function-calling format `{name, description, parameters}`, writes `tool_definitions.json`
- [x] 2.2 Run `.venv\Scripts\python.exe scripts/generate_tool_definitions.py` → commit `src/cloudops_fc/schemas/tool_definitions.json`

## Phase 3: Testing

- [x] 3.1 Update `tests/conftest.py` — add `valid_restart_payload` fixture matching new RDS schema; update existing `valid_payload` fixture for expanded EC2 schema
- [x] 3.2 Parametrize `TestMetaConformance.SCHEMA_NAMES` → `["create_ec2_instance", "restart_database"]`
- [x] 3.3 Add `TestValidPayloadRDS` class — required-only and with-failover scenarios; parametrize `TestMalformedPayloads` across both schemas (missing field, wrong type, extra field)
- [x] 3.4 Add `TestToolDefinitions` class — 4 scenarios: valid structure, matches EC2 source, matches RDS source, no extra tools

## Dependency Graph

```
1.1 (EC2 schema) ──┐
                   ├──→ 2.1 (generator) ──→ 2.2 (tool_definitions)
1.2 (RDS schema) ──┘
                   ├──→ 3.1 (fixtures)
                   ├──→ 3.2 (meta-conformance)
                   ├──→ 3.3 (validation tests)
                   └──→ 3.4 (tool definitions tests)
```

Phases 3.1–3.4 can be done in parallel after schemas exist (1.1 + 1.2 complete). Phase 2 is independent of testing — generator script can be written/tested concurrently with Phase 3.

**8 tasks total** across 3 phases. Single PR, ~330 lines, under 400-line budget.
