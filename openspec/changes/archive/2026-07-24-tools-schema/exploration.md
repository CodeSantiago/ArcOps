# Exploration: Tools Schema (Fase 1 — Function/Tool Definitions)

## Current State

The project currently has a **single seed schema** file at `src/cloudops_fc/schemas/create_ec2_instance.json` — a minimal Draft 2020-12 JSON Schema with 5 fields (`instance_type`, `ami_id`, `region`, `min_count`, `max_count`), all required, no enums or constraints. The validation framework (`schemas/__init__.py`) provides `load_schema()` and `validate_payload()` using `jsonschema`, and tests exist in `tests/unit/test_schema_validation.py` with 100% coverage confirming meta-validation, loading, valid payloads, and rejection of malformed payloads.

The conftest provides a `valid_payload` fixture with example values (`t3.micro`, `ami-0c55b159cbfafe1f0`, `us-east-1`).

Nothing else exists — no other tool schemas, no output format decisions, no AWS API mapping logic.

## Affected Areas

- `src/cloudops_fc/schemas/create_ec2_instance.json` — replace with expanded schema
- `src/cloudops_fc/schemas/restart_database.json` — new file
- `src/cloudops_fc/schemas/get_billing_alert.json` — new file
- `src/cloudops_fc/schemas/__init__.py` — refactor to load schemas by tool name
- `tests/unit/test_schema_validation.py` — extend fixtures and test cases for all three tools
- `tests/conftest.py` — add valid_payload fixtures for new tools
- (future) `src/cloudops_fc/tools/` — execution layer (out of scope for Fase 1)

## Investigation Findings

### 1. Parameter Schemas for Each Tool

#### 1.1 create_ec2_instance

**AWS API**: `EC2.RunInstances` — https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_RunInstances.html

**Required params**: ImageId (or LaunchTemplate), MinCount, MaxCount
**Key optional params**: InstanceType, KeyName, SecurityGroupIds, SubnetId, Placement, TagSpecification, UserData, IamInstanceProfile

**Proposed schema** (AWS-native, low-level):

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| region | string | YES | Enum of AWS regions (`us-east-1`, `us-west-2`, etc.) | AWS region to launch in |
| instance_type | string | YES | Enum of valid EC2 instance types (subset, or `*` pattern) | EC2 instance type |
| ami_id | string | NO | Pattern: `ami-*` | AMI ID (default if omitted) |
| min_count | integer | NO | Min: 1, Default: 1 | Minimum instances |
| max_count | integer | NO | Min: 1, Default: 1 | Maximum instances |
| key_name | string | NO | - | SSH key pair name |
| security_group_ids | array[string] | NO | - | Security group IDs |
| security_group_rules | array[object] | NO | `{port, protocol, cidr}` | Inline SG rules (for "abrime el puerto 80") |
| subnet_id | string | NO | - | Subnet ID |
| associate_public_ip | boolean | NO | Default: false | Request public IP |
| tags | array[object] | NO | `{key, value}` | Resource tags |

**Key insight from user prompt**: "Creame un servidor en la zona de Virginia con 16GB de RAM y abrime el puerto 80"
- "Virginia" → `region: "us-east-1"`
- "16GB RAM" → `instance_type: "t3.xlarge"` (16GB) — the model learns this mapping
- "abrime el puerto 80" → `security_group_rules: [{"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"}]`

The `security_group_rules` field is a **CloudOps abstraction** — it's not a native RunInstances parameter. It represents a higher-level intent that downstream execution would translate into a security group creation + attachment. This is the right level for the model to learn.

#### 1.2 restart_database

**AWS API**: `RDS.RebootDBInstance` — https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_RebootDBInstance.html

**Required params**: DBInstanceIdentifier
**Optional params**: ForceFailover

**Proposed schema**:

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| db_instance_identifier | string | YES | Pattern: lowercase alphanumeric + hyphens | RDS instance identifier |
| force_failover | boolean | NO | Default: false | Force Multi-AZ failover |
| region | string | YES | Enum of AWS regions | Region of the RDS instance |

**Note**: This is intentionally simple. The model's task is to extract the DB instance identifier from natural language ("Reiniciar base de datos — la de producción en us-west-2").

#### 1.3 get_billing_alert

**AWS API**: `Cost Explorer.GetCostAndUsage` — https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html

**Required params**: TimePeriod, Granularity, Metrics
**Key optional params**: GroupBy, Filter, BillingViewArn

**Proposed schema**:

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| time_period_start | string | NO | Date format: `YYYY-MM-DD`, Default: first day of month | Start date |
| time_period_end | string | NO | Date format: `YYYY-MM-DD`, Default: today | End date |
| granularity | string | NO | Enum: `DAILY`, `MONTHLY`, `HOURLY`. Default: `MONTHLY` | Data granularity |
| metrics | array[string] | NO | Default: `["BlendedCost"]` | Metrics to retrieve |
| group_by_service | boolean | NO | Default: false | Group costs by service |
| limit | integer | NO | Min: 1, Max: 1000, Default: 20 | Max result items |

**Note**: The "Consultar gastos del mes" prompt maps to sensible defaults — current month, MONTHLY granularity, BlendedCost. The model needs to handle variations like "gastos de este mes por servicio" (group_by_service: true).

### 2. Output Format

**Two approaches identified:**

#### Approach A: OpenAI function-calling format (RECOMMENDED)

```json
{
  "name": "create_ec2_instance",
  "arguments": {
    "region": "us-east-1",
    "instance_type": "t3.xlarge",
    "security_group_rules": [{"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"}]
  }
}
```

**Pros:**
- Matches the existing seed schema pattern (already used in scaffolding)
- Industry standard for fine-tuning (Glaive, Nexus, Gorilla datasets)
- Well-supported by HuggingFace Transformers + TRL for training
- Simple JSON structure, easy for a small LLM to learn
- `name` field enables multi-tool routing

**Cons:**
- Not directly executable as an AWS SDK call (needs translation layer, but that's future work)
- `arguments` is a nested object, requires the model to maintain JSON structure

#### Approach B: Flat AWS SDK-compatible format

```json
{
  "service": "ec2",
  "operation": "RunInstances",
  "region": "us-east-1",
  "parameters": {
    "InstanceType": "t3.xlarge",
    "MaxCount": 1,
    "MinCount": 1
  }
}
```

**Pros:**
- Directly maps to boto3 calls
- Explicit about target AWS service and operation

**Cons:**
- More complex structure (three nesting levels)
- Harder for an 8B model to learn reliably
- Breaks from the seed schema pattern
- Field names differ between schema and API (PascalCase vs camelCase)

#### Approach C: Custom compact format

```json
{
  "tool": "create_ec2_instance",
  "params": {
    "region": "us-east-1",
    "instance_type": "t3.xlarge"
  }
}
```

**Pros:**
- Simplest structure — easiest for the model to learn
- Minimal token usage per output

**Cons:**
- Non-standard — poor ecosystem compatibility
- No established fine-tuning datasets use this format
- Would require custom parsing

**Recommendation: Approach A — OpenAI function-calling format.** It aligns with the existing seed, is the most widely used format in LLM function-calling fine-tuning, and is well-supported by training frameworks. The model learns a consistent `{"name": "...", "arguments": {...}}` envelope.

### 3. Seed Refactoring

**Current seed**: `create_ec2_instance.json` with 5 flat fields, all required, no constraints.

**Decision**: **REPLACE** the seed schema. The current file was placeholder scaffolding. The new version must:
- Add `region` enum (the seed has `region` as a plain string)
- Replace loose `instance_type` with an enum of common types (or pattern validation)
- Add `security_group_rules` for the port-opening use case
- Make some fields optional (`ami_id`, `min_count`, `max_count`)
- Add `key_name`, `tags`, `associate_public_ip`, `subnet_id` as optional fields
- Keep the same `$id`, `title`, and Draft 2020-12 schema version

The schema directory and loader code remain unchanged — only the JSON file content changes, plus adding `restart_database.json` and `get_billing_alert.json`.

### 4. AWS API Alignment

| Tool (schema name) | AWS Service | AWS API | Boto3 Method |
|--------------------|-------------|---------|--------------|
| `create_ec2_instance` | EC2 | RunInstances | `ec2_client.run_instances(...)` |
| `restart_database` | RDS | RebootDBInstance | `rds_client.reboot_db_instance(...)` |
| `get_billing_alert` | Cost Explorer | GetCostAndUsage | `ce_client.get_cost_and_usage(...)` |

**Field mapping challenges**:
- The schema uses `snake_case` (Python convention) while AWS APIs use `PascalCase` — the downstream execution layer handles translation
- `security_group_rules` is a CloudOps abstraction: the model outputs port/protocol/cidr, but the actual execution would need to find or create a security group and attach it. This is a future execution-layer concern
- `region` is included in every schema — the model must output it explicitly. Downstream execution would use it to target the correct AWS client

### 5. Parameter Constraints

**create_ec2_instance**:
- `region`: Enum of 15+ major AWS regions, not the full 30+
  - Minimal set: `us-east-1`, `us-east-2`, `us-west-1`, `us-west-2`, `eu-west-1`, `eu-central-1`, `eu-west-2`, `ap-southeast-1`, `ap-southeast-2`, `ap-northeast-1`, `sa-east-1`, `ca-central-1`
  - Full set can be used if needed
- `instance_type`: Enum or pattern. The full AWS list is 300+ types. Recommended approach:
  - **Pattern-based**: `"^[a-z][0-9][a-z]+\.[0-9]?[a-z]*$"` (allow any valid type string)
  - Or a curated subset of the ~40 most common types (t3, m5, c5, r5 families)
- `security_group_rules[].protocol`: Enum `["tcp", "udp", "icmp"]`. Default: `tcp`
- `security_group_rules[].cidr`: Pattern `"^\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}/\\d{1,2}$"`. Default: `"0.0.0.0/0"`

**restart_database**:
- `db_instance_identifier`: Pattern `"^[a-z][a-z0-9-]+[a-z0-9]$"` (RDS identifier constraints)
- `region`: Same enum as EC2

**get_billing_alert**:
- `granularity`: Enum `["DAILY", "MONTHLY", "HOURLY"]`
- `metrics`: Array with enum values `["BlendedCost", "UnblendedCost", "UsageQuantity", "AmortizedCost", "NetUnblendedCost"]`
- `time_period_start` / `time_period_end`: Pattern `"^\\d{4}-\\d{2}-\\d{2}$"`

### 6. Error Cases

**What happens when the model emits invalid params?**

The existing validation framework catches ALL structural errors via JSON Schema validation:

| Error Type | Schema Mechanism | Example |
|------------|-----------------|---------|
| Missing required field | `required` keyword | Missing `region` |
| Wrong type | `type` keyword | `instance_type: 123` |
| Invalid enum value | `enum` keyword | `region: "mars-1"` |
| Extra unknown field | `additionalProperties: false` | Extra `foo: "bar"` |
| Pattern mismatch | `pattern` keyword | `ami_id: "not-an-ami"` |

**Beyond schema validation** — semantic errors that schema cannot catch:
- Unknown AMI ID (valid format `ami-xxx` but doesn't exist)
- Instance type not available in the specified region
- Insufficient account limits

**Recommendation**: The validation framework is sufficient for Fase 1. Semantic validation is an execution-layer concern (Fase 3+). The fine-tuning evaluation in Fase 2 should measure:
1. **Schema conformance rate** — % of model outputs that pass schema validation
2. **Field accuracy** — Exact-match and fuzzy-match for each field
3. **Semantic validity** — (future) whether the params would actually succeed against AWS

### 7. Relation to Fine-tuning Format

The tool schemas serve **dual purpose** in the ML pipeline:

**Purpose A — Validation (immediate, Fase 1):**
JSON Schemas express constraints for `validate_payload()`. Used in testing and evaluation to measure output quality.

**Purpose B — Tool definitions for training (Fase 2):**
The schemas must be expressible as **function definitions** in the training format. The recommended format for training data:

```
System: You are a CloudOps assistant. You have access to the following functions:
- create_ec2_instance: {schema summary}
- restart_database: {schema summary}
- get_billing_alert: {schema summary}

User: Creame un servidor en la zona de Virginia con 16GB de RAM
       y abrime el puerto 80

Assistant: {"name": "create_ec2_instance", "arguments": {...}}
```

This mirrors OpenAI's `functions` API format and is well-supported by training frameworks. Each schema needs a **compressed summary** (parameter names + types + constraints) that fits in the system prompt without exceeding the model's token budget.

**Recommendation:**
- Keep the JSON Schemas as the **source of truth** for validation
- Generate a flattened `tool_definitions.json` from the schemas for training use
- The training format should use the OpenAI `functions` schema style (type + properties + required) — which is already what JSON Schema Draft 2020-12 provides

**Note on `instance_type` enum**: The 300+ instance types will not fit in a system prompt for an 8B model. Recommendation:
- Use a curated subset (~40 common types) for the schema enum
- The model learns the general pattern and can generalize to unseen types
- Or use a pattern constraint instead of an enum

### 8. Region Enum Design Decision

The user's example "zona de Virginia" → `us-east-1` is a region mapping the model must learn. This requires the model to know:
- Virginia → us-east-1
- Oregon → us-west-2
- Frankfurt → eu-central-1
- etc.

The region enum in the schema should use **AWS region codes** (not human names). The NL-to-region mapping is part of what the fine-tuning teaches.

## Approaches

### Approach 1: Flat per-tool schemas — extend existing pattern

Keep the existing `schemas/__init__.py` pattern. One JSON Schema file per tool. `load_schema("create_ec2_instance")` returns the schema dict. Validation uses the existing `validate_payload()`.

- **Pros**: Zero refactoring of validation infrastructure. Matches current code organization. Simple to test.
- **Cons**: Doesn't handle the tool-definitions concept (training format needs separate conversion).
- **Effort**: Low

### Approach 2: Tool registry with metadata

Create a `tools/` module that wraps each schema with metadata: tool name, description, parameter summary, AWS API mapping. Schemas remain as JSON files but are loaded through a registry.

```python
# registry concept
tools = {
    "create_ec2_instance": {
        "name": "create_ec2_instance",
        "description": "Launch an EC2 instance",
        "schema": load_schema("create_ec2_instance"),
        "aws_service": "ec2",
        "aws_operation": "RunInstances",
        "parameter_summary": {...},
    }
}
```

- **Pros**: Single source of truth for training format generation. Cleaner abstraction layer. AWS API metadata is explicit.
- **Cons**: More code to write and test. Over-engineered for Fase 1 — nothing consumes the AWS API metadata yet.
- **Effort**: Medium

### Approach 3: Schema generation from Python dataclasses

Define schemas as Python dataclasses with type hints and validation decorators. Generate JSON Schema from the dataclass definitions.

- **Pros**: Type-safe. DRY — no duplication between schema and Python code.
- **Cons**: Requires a schema generation library or custom code. Adds dependency. Over-engineered for 3 tools.
- **Effort**: High

## Recommendation

**Approach 1 — Flat per-tool schemas.** For Fase 1, the simplest approach is the right one:

1. **Replace** `create_ec2_instance.json` with the expanded schema (add region enum, security_group_rules, make optional fields optional)
2. **Create** `restart_database.json` and `get_billing_alert.json` following the same pattern
3. **Extend** `conftest.py` with valid payload fixtures for each tool
4. **Extend** test cases — parametrize existing tests to run against all 3 schemas
5. **Keep** the output format as `{"name": "...", "arguments": {...}}` (OpenAI function-calling format)
6. **Do NOT** build the tool registry or execution layer — those are future Fases

The tool-definitions-for-training concern (Purpose B in section 7) is noted for Fase 2 but doesn't block Fase 1 schema work.

## Risks

1. **`instance_type` enum bloat**: 300+ EC2 types. Using the full enum makes schemas too large for training context. Mitigation: use a pattern constraint (`^[a-z][0-9][a-z]+\\.[0-9]?[a-z]*$`) or a curated ~40-type subset. Document the tradeoff.
2. **Region enum completeness**: AWS adds new regions regularly. A hardcoded enum will go stale. Mitigation: use a minimal but stable set of major regions. Accept that the schema may need maintenance.
3. **`security_group_rules` abstraction gap**: This field is a CloudOps abstraction, not a direct AWS API param. If the intent is pure AWS API alignment, this should be removed. But it directly enables the "abrime el puerto 80" use case. Mitigation: keep it, add clear documentation that downstream translation is required.
4. **Schema ↔ training format drift**: If the schemas are updated after Fase 2 begins, the training dataset must be regenerated. Mitigation: treat the schema directory as source of truth; the training pipeline should generate tool definitions from schemas programmatically.
5. **Testing scope**: Moving from 1 schema to 3 means 3x the test parametrization. The existing test class `TestMetaConformance` already has `SCHEMA_NAMES = ["create_ec2_instance"]` — this needs to be extended. Straightforward but requires discipline.

## Ready for Proposal

**Yes.** The exploration is thorough enough to inform a proposal. Key decisions the proposal should address:
1. Confirm `{"name", "arguments"}` output format (Approach A)
2. Confirm per-tool schema file pattern (Approach 1 for schema organization)
3. Decide on `instance_type` constraint — enum subset or pattern?
4. Decide on `region` enum — minimal major set or expanded?
5. Decide whether to include `security_group_rules` as a CloudOps abstraction
6. Decide on the `get_billing_alert` parameter set — minimal (just sensible defaults) or full with all Cost Explorer options?
