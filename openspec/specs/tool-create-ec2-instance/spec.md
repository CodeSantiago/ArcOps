# Tool Schema: create_ec2_instance

## Purpose

Define the JSON Schema for the `create_ec2_instance` function-calling tool — launching EC2 instances with CloudOps abstractions. Part of the CloudOps function-calling fine-tuning pipeline.

---

## Requirements

### R1: Schema Structure

The `create_ec2_instance` schema MUST be a Draft 2020-12 `object` with `additionalProperties: false`.

#### Scenario: Meta-schema passes
- GIVEN the `create_ec2_instance` schema file
- WHEN validated against the Draft 2020-12 meta-schema
- THEN validation MUST succeed

### R2: Required Fields

| Field | Type | Constraint |
|-------|------|------------|
| `region` | string | Enum: `us-east-1`, `us-east-2`, `us-west-1`, `us-west-2`, `eu-west-1`, `eu-central-1`, `eu-west-2`, `ap-southeast-1`, `ap-southeast-2`, `ap-northeast-1`, `sa-east-1`, `ca-central-1` |
| `instance_type` | string | Pattern: `^[a-z][0-9]+\.(micro\|small\|medium\|large\|xlarge\|[0-9]+xlarge)$` |

### R3: Optional Fields

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

---

## Scenarios

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

## Source Schema

File: `src/cloudops_fc/schemas/create_ec2_instance.json`
