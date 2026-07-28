# Tools Schema — Specification

## Purpose

Define two production-ready JSON Schema tool definitions (`create_ec2_instance`, `restart_database`) in OpenAI function-calling format for the fine-tuning pipeline. Produce a training-ready `tool_definitions.json` aggregate. Extend schema-validation coverage from 1 to 2 schemas.

---

## Domain: tool-create-ec2-instance

### Requirements

#### R1: Schema Structure
The `create_ec2_instance` schema MUST be a Draft 2020-12 `object` with `additionalProperties: false`.

#### R2: Required Fields

| Field | Type | Constraint |
|-------|------|------------|
| `region` | string | Enum: `us-east-1`, `us-east-2`, `us-west-1`, `us-west-2`, `eu-west-1`, `eu-central-1`, `eu-west-2`, `ap-southeast-1`, `ap-southeast-2`, `ap-northeast-1`, `sa-east-1`, `ca-central-1` |
| `instance_type` | string | Pattern: `^[a-z][0-9][a-z]+\.[0-9]+[a-z]+$` |

#### R3: Optional Fields

| Field | Type | Default | Constraint |
|-------|------|---------|------------|
| `ami_id` | string | — | Pattern: `^ami-` |
| `min_count` | integer | 1 | Minimum: 1 |
| `max_count` | integer | 1 | Minimum: 1 |
| `key_name` | string | — | — |
| `security_group_rules` | array[object] | — | Items: `{port: int, protocol: enum[tcp,udp,icmp], cidr: string}` |
| `subnet_id` | string | — | — |
| `associate_public_ip` | boolean | false | — |
| `tags` | array[object] | — | Items: `{key: string, value: string}` |

#### Scenarios

| # | Scenario | GIVEN | WHEN | THEN |
|---|----------|-------|------|------|
| S1 | Valid payload — required only | `create_ec2_instance` schema | Payload: `{"region":"us-east-1","instance_type":"t3.xlarge"}` | Validation MUST succeed |
| S2 | Valid payload — all fields | Same schema | Payload with all optional fields and correct types | Validation MUST succeed |
| S3 | Missing required field | Same schema | Payload omits `region` | Validation MUST fail, names missing field |
| S4 | Invalid instance_type pattern | Same schema | `instance_type` is `"invalid"` | Validation MUST fail, pattern mismatch |
| S5 | Invalid region enum | Same schema | `region` is `"mars-1"` | Validation MUST fail, enum error |
| S6 | Extra unknown field | Same schema | Payload includes `"foo":"bar"` | Validation MUST fail |
| S7 | Wrong type | Same schema | `min_count` is string `"one"` | Validation MUST fail, type mismatch |
| S8 | security_group_rules valid | Same schema | `security_group_rules: [{"port":80,"protocol":"tcp","cidr":"0.0.0.0/0"}]` | Validation MUST succeed |

---

## Domain: tool-restart-database

### Requirements

#### R1: Schema Structure
The `restart_database` schema MUST be a Draft 2020-12 `object` with `additionalProperties: false`.

#### R2: Required Fields

| Field | Type | Constraint |
|-------|------|------------|
| `db_instance_identifier` | string | Pattern: `^[a-z][a-z0-9-]+[a-z0-9]$` |
| `region` | string | Same 12-region enum as create_ec2_instance |

#### R3: Optional Fields

| Field | Type | Default | Constraint |
|-------|------|---------|------------|
| `force_failover` | boolean | false | — |

#### Scenarios

| # | Scenario | GIVEN | WHEN | THEN |
|---|----------|-------|------|------|
| S1 | Valid payload — required | `restart_database` schema | Payload: `{"db_instance_identifier":"prod-primary","region":"us-west-2"}` | Validation MUST succeed |
| S2 | Valid payload — with force_failover | Same schema | Payload includes `force_failover: true` | Validation MUST succeed |
| S3 | Missing required field | Same schema | Payload omits `db_instance_identifier` | Validation MUST fail, names missing field |
| S4 | Invalid identifier pattern | Same schema | `db_instance_identifier` is `"Invalid_Name!"` | Validation MUST fail, pattern mismatch |
| S5 | Extra unknown field | Same schema | Payload includes `"unexpected":"value"` | Validation MUST fail |

---

## Domain: tool-definitions

### Requirements

#### R1: OpenAI Functions-Calling Format
`tool_definitions.json` MUST be a JSON array where each entry has `name` (string), `description` (string), and `parameters` (JSON Schema).

Example entry:

```json
{
  "name": "create_ec2_instance",
  "description": "Launch an EC2 instance in the specified region",
  "parameters": {
    "type": "object",
    "properties": {
      "region": { "type": "string", "enum": ["us-east-1", "us-west-2", "..."] },
      "instance_type": { "type": "string", "pattern": "^[a-z][0-9][a-z]+\\.[0-9]+[a-z]+$" }
    },
    "required": ["region", "instance_type"],
    "additionalProperties": false
  }
}
```

#### R2: Completeness
The file MUST contain exactly 2 entries: `create_ec2_instance` and `restart_database`.

#### R3: Schema Consistency
Each entry's `parameters` MUST match its source schema — field names, types, constraints, and required list MUST be equivalent.

#### R4: No Execution Metadata
Entries MUST NOT include AWS service, operation, or boto3 client fields.

#### Scenarios

| # | Scenario | GIVEN | WHEN | THEN |
|---|----------|-------|------|------|
| S1 | Valid structure | `tool_definitions.json` | Parsed as JSON | Array of 2+ entries with OpenAI schema style |
| S2 | Matches ec2 source | Source `create_ec2_instance` schema | Compared with matching entry `parameters` | MUST be functionally equivalent |
| S3 | Matches rds source | Source `restart_database` schema | Compared with matching entry `parameters` | MUST be functionally equivalent |
| S4 | No extra tools | `tool_definitions.json` | Listed by `name` | Only `create_ec2_instance` and `restart_database` present |

---

## Domain: schema-validation (Delta)

### MODIFIED Requirements

#### R2: Valid Payload Acceptance (Previously: covered create_ec2_instance only)

A payload matching all schema constraints SHALL pass validation. This MUST hold for both `create_ec2_instance` and `restart_database` schemas.

##### Scenario: create_ec2_instance valid payload (Unchanged)
- GIVEN the `create_ec2_instance` schema
- WHEN a valid payload is validated
- THEN result MUST indicate success

##### Scenario: restart_database valid payload (Added)
- GIVEN the `restart_database` schema
- WHEN a valid payload is validated
- THEN result MUST indicate success

#### R3: Malformed Payload Rejection (Previously: covered create_ec2_instance only)

An invalid payload MUST be rejected with a clear error message. This MUST hold for both schemas.

##### Scenario: Missing required field (Parametrized)
- GIVEN either `create_ec2_instance` or `restart_database` schema
- WHEN any required field is omitted
- THEN validation MUST fail, naming the missing field

##### Scenario: Wrong value type (Parametrized)
- GIVEN either schema with a typed field
- WHEN the field has the wrong type (string for integer)
- THEN validation MUST fail, type-mismatch error

##### Scenario: Extra unknown field (Parametrized)
- GIVEN either schema with `additionalProperties: false`
- WHEN payload includes an unrecognized field
- THEN validation MUST fail

---

## Coverage Summary

| Domain | Type | Requirements | Scenarios |
|--------|------|-------------|-----------|
| tool-create-ec2-instance | New | R1-R3 | 8 |
| tool-restart-database | New | R1-R3 | 5 |
| tool-definitions | New | R1-R4 | 4 |
| schema-validation | Delta | R2, R3 modified | 5 |
| **Total** | — | **10 requirements** | **22 scenarios** |
