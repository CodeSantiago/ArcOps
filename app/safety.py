"""ArcOps Safety Layer — Guardrails, Cost Estimation & Security Policies.

Sits between the model output and AWS execution.
Validates, estimates costs, and enforces policies before any action runs.
"""
import json, os, re
from datetime import datetime
from typing import Optional

# ── AWS Pricing (hardcoded approximations for common instance types) ─────
# Source: AWS public pricing (us-east-1, Linux, On-Demand)
EC2_PRICING = {
    "t3.nano":    0.0052,   "t3.micro":   0.0104,   "t3.small":   0.0208,
    "t3.medium":  0.0416,   "t3.large":   0.0832,   "t3.xlarge":  0.1664,
    "t2.micro":   0.0116,   "t2.small":   0.0230,   "t2.medium":  0.0464,
    "m5.large":   0.0960,   "m5.xlarge":  0.1920,   "m5.2xlarge": 0.3840,
    "c6i.large":  0.0850,   "c6i.xlarge": 0.1700,   "c6i.2xlarge":0.3400,
    "r5.large":   0.1260,   "r5.xlarge":  0.2520,   "r5.2xlarge": 0.5040,
}

RDS_PRICING = {
    "db.t3.micro":    0.017,  "db.t3.small":    0.034,
    "db.t3.medium":   0.068,  "db.t3.large":    0.136,
    "db.r5.large":    0.240,  "db.r5.xlarge":   0.480,
}

HOURS_PER_MONTH = 730  # average

# ── Schema definitions ───────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "create_ec2_instance": {
        "required": ["region", "instance_type"],
        "optional": ["ami_id", "key_name", "security_group_rules", "subnet_id",
                     "associate_public_ip", "tags", "min_count", "max_count"],
        "allowed": {   # set of ALL valid parameter names
            "region", "instance_type", "ami_id", "key_name",
            "security_group_rules", "subnet_id", "associate_public_ip",
            "tags", "min_count", "max_count"
        },
        "destructive": False,
    },
    "restart_database": {
        "required": ["db_instance_identifier", "region"],
        "optional": ["force_failover"],
        "allowed": {"db_instance_identifier", "region", "force_failover"},
        "destructive": False,
        "disruptive": True,  # causes downtime
    },
    "get_billing_alert": {
        "required": [],
        "optional": ["time_period_start", "time_period_end", "granularity",
                     "metrics", "group_by_service"],
        "allowed": {"time_period_start", "time_period_end", "granularity",
                    "metrics", "group_by_service"},
        "destructive": False,
    },
}


# ── Safety Layer ─────────────────────────────────────────────────────────

class SafetyResult:
    """Result of a safety check."""
    def __init__(self):
        self.passed = True
        self.warnings = []
        self.errors = []
        self.estimated_cost = 0.0
        self.blocked = False
        self.requires_approval = False

    def to_dict(self):
        return {
            "passed": self.passed and not self.blocked,
            "warnings": self.warnings,
            "errors": self.errors,
            "estimated_cost_monthly": round(self.estimated_cost, 2),
            "blocked": self.blocked,
            "requires_approval": self.requires_approval,
        }

    def __str__(self):
        parts = []
        if self.blocked:
            parts.append("BLOCKED")
        elif self.passed:
            parts.append("PASS")
        if self.warnings:
            parts.append(f"Warnings: {len(self.warnings)}")
        if self.estimated_cost:
            parts.append(f"~${self.estimated_cost:.0f}/mo")
        if self.requires_approval:
            parts.append("Requires approval")
        return " | ".join(parts) if parts else "PASS"


def validate_schema(tool_name: str, arguments: dict) -> SafetyResult:
    """Validate tool call against schema. Rejects hallucinated parameters."""
    result = SafetyResult()
    schema = TOOL_SCHEMAS.get(tool_name)

    if not schema:
        result.errors.append(f"Unknown tool: {tool_name}")
        result.passed = False
        return result

    # Check for hallucinated parameters (not in schema)
    for key in arguments:
        if key not in schema["allowed"]:
            result.errors.append(
                f"Unknown parameter '{key}' — not in {tool_name} schema. "
                f"Valid params: {', '.join(sorted(schema['allowed']))}"
            )
            result.blocked = True

    # Check required params
    for key in schema["required"]:
        if key not in arguments or arguments[key] is None:
            result.errors.append(f"Missing required parameter: {key}")

    # Check for empty/trivial arguments on tools that require them
    if tool_name == "create_ec2_instance" and not arguments.get("instance_type"):
        result.warnings.append("No instance type specified — using default (t3.micro)")

    if result.errors:
        result.passed = False
    return result


def estimate_cost(tool_name: str, arguments: dict) -> SafetyResult:
    """Estimate monthly cost for the requested action."""
    result = SafetyResult()

    if tool_name == "create_ec2_instance":
        inst = arguments.get("instance_type", "t3.micro")
        count = arguments.get("min_count", 1)
        price = EC2_PRICING.get(inst)
        if price:
            monthly = price * HOURS_PER_MONTH * count
            result.estimated_cost = monthly
            result.warnings.append(
                f"Estimated cost: ~${monthly:.0f}/mo ({inst} x{count})"
            )
        else:
            result.warnings.append(f"Price not found for {inst} — check AWS pricing")

    elif tool_name == "restart_database":
        result.warnings.append("No additional cost for restart (same-hour billing)")

    elif tool_name == "get_billing_alert":
        result.warnings.append("Read-only operation — no cost")

    return result


def apply_policies(tool_name: str, arguments: dict, env: str = "production") -> SafetyResult:
    """Apply security policies based on environment and action."""
    result = SafetyResult()
    schema = TOOL_SCHEMAS.get(tool_name)
    if not schema:
        return result

    # Block destructive actions in production
    if schema.get("destructive") and env == "production":
        result.blocked = True
        result.errors.append(
            f"BLOCKED: {tool_name} is destructive and not allowed in {env} environment"
        )

    # Flag disruptive actions (cause downtime)
    if schema.get("disruptive") and env == "production":
        result.warnings.append(
            f"{tool_name} will cause downtime. Ensure maintenance window."
        )
        result.requires_approval = True

    return result


def check(tool_name: str, arguments: dict, env: str = "production") -> SafetyResult:
    """Run all safety checks. Returns combined result."""
    results = []

    # 1. Schema validation
    r1 = validate_schema(tool_name, arguments)
    results.append(r1)

    # 2. Cost estimation
    r2 = estimate_cost(tool_name, arguments)
    results.append(r2)

    # 3. Security policies
    r3 = apply_policies(tool_name, arguments, env)
    results.append(r3)

    # Combine
    final = SafetyResult()
    for r in results:
        final.passed = final.passed and r.passed
        final.blocked = final.blocked or r.blocked
        final.requires_approval = final.requires_approval or r.requires_approval
        final.warnings.extend(r.warnings)
        final.errors.extend(r.errors)
        final.estimated_cost += r.estimated_cost

    return final


# ── CLI entry point ──────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="ArcOps Safety Layer — validate & estimate cost")
    parser.add_argument("tool_call_json", help="Tool call JSON string or file path")
    parser.add_argument("--env", default="production", choices=["development", "staging", "production"])
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Input can be a JSON string or a file path
    raw = args.tool_call_json
    if os.path.exists(raw):
        raw = open(raw).read()

    try:
        tc = json.loads(raw)
    except json.JSONDecodeError:
        print("Invalid JSON")
        return

    tool_name = tc.get("name", tc.get("tool", ""))
    arguments = tc.get("arguments", tc.get("parameters", {}))

    result = check(tool_name, arguments, args.env)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"\n  Safety check for: {tool_name}")
        print(f"  Status: {result}")
        if result.warnings:
            for w in result.warnings:
                print(f"  Warning: {w}")
        if result.errors:
            for e in result.errors:
                print(f"  Error: {e}")
        if result.blocked:
            print(f"  Action BLOCKED by security policy")
        elif result.requires_approval:
            print(f"  Action requires manual approval")


if __name__ == "__main__":
    main()
