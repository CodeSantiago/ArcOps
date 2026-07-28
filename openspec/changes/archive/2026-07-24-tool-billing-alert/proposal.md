# Proposal: Tool get_billing_alert

## Intent

Complete the 3-tool set by adding `get_billing_alert` — deferred from the tools-schema change. Billing queries ("¿cuánto gasté este mes?") are a core CloudOps use case. Without this tool, the model can't answer cost-related instructions, limiting the assistant's practical value.

## Scope

### In Scope
- Create `get_billing_alert.json` schema (Cost Explorer GetCostAndUsage)
- Add tool entry to `tool_definitions.json` (auto-generated via existing script)
- Update spec R2 from 2 entries → 3 entries
- Test fixtures and parametrized validation for the new tool

### Out of Scope
- Execution layer / boto3 integration (deferred)
- Complex Cost Explorer features (GroupBy, Filter, BillingViewArn)
- Semantic validation of billing parameters against real AWS data

## Capabilities

### New Capabilities
- `billing-alert`: `get_billing_alert` tool schema — parameters for time period, granularity, metrics, and service grouping. Transforms NL billing queries into structured Cost Explorer params.

### Modified Capabilities
- `tool-definitions`: R2 updates from "exactly 2 entries" to "exactly 3 entries". Scenarios S4 updated accordingly.

## Approach

**Schema** (OpenAI function-calling format):

| Field | Type | Required | Constraints | Default |
|-------|------|----------|-------------|---------|
| time_period_start | string | NO | Pattern: `\d{4}-\d{2}-\d{2}` | First day of current month |
| time_period_end | string | NO | Pattern: `\d{4}-\d{2}-\d{2}` | Today |
| granularity | string | NO | Enum: `DAILY`, `MONTHLY`, `HOURLY` | `MONTHLY` |
| metrics | array[string] | NO | Enum: `BlendedCost`, `UnblendedCost`, `UsageQuantity`, `AmortizedCost`, `NetUnblendedCost` | `["BlendedCost"]` |
| group_by_service | boolean | NO | — | `false` |

**Generation**: Existing `scripts/generate_tool_definitions.py` auto-discovers `.json` files in `schemas/`. Adding `get_billing_alert.json` means zero script changes — the tool entry appears in `tool_definitions.json` automatically on next `uv run python scripts/generate_tool_definitions.py`.

**Training format**: Same `{"name": "get_billing_alert", "arguments": {...}}` envelope. NL examples: "gastos de este mes" → defaults; "gastos de este mes por servicio" → `group_by_service: true`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/cloudops_fc/schemas/get_billing_alert.json` | **New** | Tool schema |
| `src/cloudops_fc/schemas/tool_definitions.json` | **Modified** | Regenerated (2 → 3 entries) |
| `openspec/specs/tool-definitions/spec.md` | **Modified** | R2 updated to 3 entries, S4 updated |
| `tests/unit/test_schema_validation.py` | **Modified** | Add billing-alert parametrization |
| `tests/conftest.py` | **Modified** | Add `get_billing_alert` valid payload fixture |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Date format mismatch (model outputs wrong format) | Medium | Schema pattern validation catches it. Add invalid-date test cases. |
| Region enum not applicable (billing is global) | Low | Cost Explorer is a global service — no `region` param needed in this schema. Clarify in docs. |
| Metrics enum too restrictive | Low | Core 5 metrics cover common queries. Extend later if needed. |

## Rollback Plan

Single-commit addition. Rollback: revert the schema file and regenerate `tool_definitions.json`. The existing 2-tool set is untouched — no migration needed.

## Dependencies

None. `generate_tool_definitions.py` handles the new file automatically.

## Success Criteria

- [ ] `get_billing_alert.json` validates against meta-schema and passes all test cases
- [ ] `tool_definitions.json` auto-generates with 3 entries after script run
- [ ] All existing 2-tool tests continue to pass
- [ ] Parametrized validation covers billing payload: defaults, explicit fields, invalid dates
