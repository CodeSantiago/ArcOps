"""ArcOps canonical safety layer — validation, cost estimation, policies.

This is the single safety module used by the CLI, API, MCP server,
``app/exec.py``, and the TUI. It validates tool calls against the tool
schemas (rejecting unknown parameters and missing required fields), estimates
monthly cost, and applies environment policies before any action executes.

Design rules enforced here:

- Unknown parameters are BLOCKED (hallucinated keys are rejected).
- Missing required fields are BLOCKED (no silent defaults like ``test-db``).
- Unknown tools are BLOCKED.
- Destructive tools are blocked in the ``production`` environment.
- Disruptive tools (downtime) raise ``requires_approval``.

The module has no torch/transformers dependency and is unit-testable.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# ── AWS pricing (hardcoded approximations, us-east-1 Linux On-Demand) ─────
EC2_PRICING: dict[str, float] = {
    "t3.nano": 0.0052, "t3.micro": 0.0104, "t3.small": 0.0208,
    "t3.medium": 0.0416, "t3.large": 0.0832, "t3.xlarge": 0.1664,
    "t2.micro": 0.0116, "t2.small": 0.0230, "t2.medium": 0.0464,
    "m5.large": 0.0960, "m5.xlarge": 0.1920, "m5.2xlarge": 0.3840,
    "c6i.large": 0.0850, "c6i.xlarge": 0.1700, "c6i.2xlarge": 0.3400,
    "r5.large": 0.1260, "r5.xlarge": 0.2520, "r5.2xlarge": 0.5040,
}

RDS_PRICING: dict[str, float] = {
    "db.t3.micro": 0.017, "db.t3.small": 0.034,
    "db.t3.medium": 0.068, "db.t3.large": 0.136,
    "db.r5.large": 0.240, "db.r5.xlarge": 0.480,
}

HOURS_PER_MONTH = 730  # average

# ── Tool schemas (mirrors src/cloudops_fc/schemas/*.json) ────────────────
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "create_ec2_instance": {
        "required": ["region", "instance_type"],
        "allowed": {
            "region", "instance_type", "ami_id", "key_name",
            "security_group_rules", "subnet_id", "associate_public_ip",
            "tags", "min_count", "max_count",
        },
        "destructive": False,
        "disruptive": False,
    },
    "restart_database": {
        "required": ["db_instance_identifier", "region"],
        "allowed": {"db_instance_identifier", "region", "force_failover"},
        "destructive": False,
        "disruptive": True,  # causes downtime
    },
    "get_billing_alert": {
        "required": [],
        "allowed": {
            "time_period_start", "time_period_end", "granularity",
            "metrics", "group_by_service",
        },
        "destructive": False,
        "disruptive": False,
    },
}


class SafetyResult:
    """Result of a safety check."""

    def __init__(self) -> None:
        self.passed = True
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.estimated_cost = 0.0
        self.blocked = False
        self.requires_approval = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {
            "passed": self.passed and not self.blocked,
            "warnings": self.warnings,
            "errors": self.errors,
            "estimated_cost_monthly": round(self.estimated_cost, 2),
            "blocked": self.blocked,
            "requires_approval": self.requires_approval,
        }

    def __str__(self) -> str:
        parts: list[str] = []
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


def _schema_for(tool_name: str) -> dict[str, Any] | None:
    return TOOL_SCHEMAS.get(tool_name)


def validate_schema(tool_name: str, arguments: dict[str, Any]) -> SafetyResult:
    """Reject unknown tools, hallucinated parameters, and missing requireds."""
    result = SafetyResult()
    schema = _schema_for(tool_name)

    if schema is None:
        result.errors.append(f"Unknown tool: {tool_name}")
        result.passed = False
        result.blocked = True
        return result

    for key in arguments:
        if key not in schema["allowed"]:
            result.errors.append(
                f"Unknown parameter '{key}' — not in {tool_name} schema. "
                f"Valid params: {', '.join(sorted(schema['allowed']))}"
            )
            result.blocked = True

    for key in schema["required"]:
        if key not in arguments or arguments[key] is None:
            result.errors.append(f"Missing required parameter: {key}")
            result.blocked = True

    if tool_name == "create_ec2_instance" and not arguments.get("instance_type"):
        result.warnings.append(
            "No instance type specified — using default (t3.micro)"
        )

    if result.errors:
        result.passed = False
    return result


def estimate_cost(tool_name: str, arguments: dict[str, Any]) -> SafetyResult:
    """Estimate the monthly cost of the requested action."""
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
            result.warnings.append(
                f"Price not found for {inst} — check AWS pricing"
            )
    elif tool_name == "restart_database":
        result.warnings.append("No additional cost for restart (same-hour billing)")
    elif tool_name == "get_billing_alert":
        result.warnings.append("Read-only operation — no cost")

    return result


def apply_policies(
    tool_name: str, arguments: dict[str, Any], env: str = "production"
) -> SafetyResult:
    """Apply security policies based on environment and action type."""
    result = SafetyResult()
    schema = _schema_for(tool_name)
    if schema is None:
        return result

    if schema.get("destructive") and env == "production":
        result.blocked = True
        result.errors.append(
            f"BLOCKED: {tool_name} is destructive and not allowed in "
            f"{env} environment"
        )

    if schema.get("disruptive") and env == "production":
        result.warnings.append(
            f"{tool_name} will cause downtime. Ensure a maintenance window."
        )
        result.requires_approval = True

    return result


def check(
    tool_name: str, arguments: dict[str, Any], env: str = "production"
) -> SafetyResult:
    """Run all safety checks and return the combined result."""
    results = [
        validate_schema(tool_name, arguments),
        estimate_cost(tool_name, arguments),
        apply_policies(tool_name, arguments, env),
    ]

    final = SafetyResult()
    for r in results:
        final.passed = final.passed and r.passed
        final.blocked = final.blocked or r.blocked
        final.requires_approval = final.requires_approval or r.requires_approval
        final.warnings.extend(r.warnings)
        final.errors.extend(r.errors)
        final.estimated_cost += r.estimated_cost

    return final


# ── CLI entry point (python -m cloudops_fc.safety) ───────────────────────

def main() -> None:
    """Validate a tool call from a JSON string or file path."""
    import argparse

    parser = argparse.ArgumentParser(
        description="ArcOps safety layer — validate and estimate cost"
    )
    parser.add_argument("tool_call_json", help="Tool call JSON string or file path")
    parser.add_argument(
        "--env",
        default="production",
        choices=["development", "staging", "production"],
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    raw = args.tool_call_json
    if os.path.exists(raw):
        raw = open(raw, encoding="utf-8").read()

    try:
        tc = json.loads(raw)
    except json.JSONDecodeError:
        print("Invalid JSON")
        sys.exit(2)

    tool_name = tc.get("name", tc.get("tool", ""))
    arguments = tc.get("arguments", tc.get("parameters", {}))

    result = check(tool_name, arguments, args.env)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    print(f"\n  Safety check for: {tool_name}")
    print(f"  Status: {result}")
    for w in result.warnings:
        print(f"  Warning: {w}")
    for e in result.errors:
        print(f"  Error: {e}")
    if result.blocked:
        print("  Action BLOCKED by safety policy")
    elif result.requires_approval:
        print("  Action requires manual approval")


if __name__ == "__main__":
    main()
