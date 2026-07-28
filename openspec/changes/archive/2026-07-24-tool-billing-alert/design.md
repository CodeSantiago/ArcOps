# Design: get_billing_alert — Tool Schema for AWS Cost Explorer

## Technical Approach

Create a Draft 2020-12 JSON Schema file for `get_billing_alert` following the existing per-tool pattern (`create_ec2_instance.json`, `restart_database.json`). The existing `generate_tool_definitions.py` auto-discovers `.json` files in the schemas directory — adding the file is sufficient; zero script changes. After regeneration, `tool_definitions.json` grows from 2 → 3 entries. Tests extend parametrization lists to cover 3 schemas, and a billing-specific payload fixture is added to conftest.

## Architecture Decisions

### Decision: Field naming follows spec, not binding decision shorthand

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `metric` (singular, per binding decision) | Doesn't match AWS Cost Explorer API which supports multiple metrics | **Rejected** |
| `metrics` (array, per spec) | Supports multiple metrics in one call, matches spec's detailed design | **Adopted** |

### Decision: All parameters optional — no `required` key

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Omit `required` | Sensible defaults produce valid output from empty args | **Adopted** |
| Make `time_period` required | Forces model to always produce dates for even simple queries | Rejected — defeats NL simplicity goal |

### Decision: No region parameter

**Rationale**: AWS Cost Explorer is a global service. A `region` param would be misleading (valid values would be silently ignored at execution time, which is out of scope). Combined with `additionalProperties: false`, any payload carrying `region` is rejected at validation.

### Decision: Schema lives in existing `schemas/` dir

**Rationale**: The generation script globs `*.json` in that directory. A subdirectory would require script changes. Keeping it flat maintains the convention.

## Data Flow

```
get_billing_alert.json ──► generate_tool_definitions.py ──► tool_definitions.json ──► inference pipeline
    (new schema)              (auto-discovers, zero                             (reads aggregate via
                              changes to script)                                importlib.resources)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/cloudops_fc/schemas/get_billing_alert.json` | **Create** | Draft 2020-12 schema — all params optional |
| `src/cloudops_fc/schemas/tool_definitions.json` | **Modify** | Regenerated: 2 → 3 entries |
| `tests/conftest.py` | **Modify** | Add `valid_billing_payload` fixture |
| `tests/unit/test_schema_validation.py` | **Modify** | Update `SCHEMA_NAMES` lists, add billing test class, update S4 to 3 tools |

## Interfaces / Contracts

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/cloudops-fc/schemas/get_billing_alert.json",
  "title": "Get Billing Alert",
  "description": "Retrieve AWS cost and usage data via Cost Explorer",
  "type": "object",
  "properties": {
    "time_period_start": {
      "type": "string",
      "pattern": "\\d{4}-\\d{2}-\\d{2}",
      "description": "Start date (YYYY-MM-DD)"
    },
    "time_period_end": {
      "type": "string",
      "pattern": "\\d{4}-\\d{2}-\\d{2}",
      "description": "End date (YYYY-MM-DD)"
    },
    "granularity": {
      "type": "string",
      "enum": ["DAILY", "MONTHLY", "HOURLY"],
      "description": "Data aggregation granularity"
    },
    "metrics": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": ["BlendedCost", "UnblendedCost", "UsageQuantity", "AmortizedCost", "NetUnblendedCost"]
      },
      "description": "Cost/metric types to retrieve"
    },
    "group_by_service": {
      "type": "boolean",
      "description": "Group results by AWS service"
    }
  },
  "additionalProperties": false
}
```

The OpenAI entry in `tool_definitions.json` will read `name` from the filename stem, `description` from the schema's `description` field, and `parameters` from schema's `{type, properties, additionalProperties}` keys. No `required` key → no `required` in the generated entry.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Meta-schema conformance | Extend `SCHEMA_NAMES` in `TestMetaConformance` to include `"get_billing_alert"` |
| Unit | Importlib loading | Same — `SCHEMA_NAMES` update covers it |
| Unit | Valid payloads | New `TestValidPayloadBilling` class: empty `{}`, defaults-only, all fields explicit |
| Unit | Invalid payloads | Extend `TestMalformedPayloads` `SCHEMA_NAMES`; new billing-specific tests: invalid dates, bad enums, wrong types, extra fields, `region` rejection |
| Unit | Tool definitions | Update `test_no_extra_tools` (S4) to `["create_ec2_instance", "get_billing_alert", "restart_database"]`. Add billing description check |
| Unit | Regression | All existing parametrized tests untouched — only list additions |

Parametrization pattern: extend class-level `SCHEMA_NAMES` lists. Billing-specific validation (no required fields, date patterns, enums) goes in a dedicated `TestValidPayloadBilling` class following the existing `TestValidPayloadRDS` pattern.

**conftest**: New `valid_billing_payload` fixture providing a full-parameter billing payload.

## Migration / Rollout

No migration required. Single-commit additive change. Rollback: delete `get_billing_alert.json` and regenerate `tool_definitions.json`.

## Open Questions

None.
