"""Test safety layer with various scenarios."""
import sys, json
sys.path.insert(0, ".")
from app.safety import check

tests = [
    ("Hallucinated param", "restart_database", {"db_instance_identifier": "analytics-rds", "region": "us-east-1", "log_event": True}),
    ("Missing required", "restart_database", {"region": "us-east-1"}),
    ("Valid EC2", "create_ec2_instance", {"region": "us-east-1", "instance_type": "t3.micro"}),
    ("EC2 with tags", "create_ec2_instance", {"region": "us-west-2", "instance_type": "m5.large", "tags": [{"key": "Name", "value": "web"}]}),
    ("RDS restart (disruptive)", "restart_database", {"db_instance_identifier": "prod-db", "region": "us-east-1", "force_failover": True}),
    ("Billing (read-only)", "get_billing_alert", {"granularity": "MONTHLY"}),
    ("Unknown tool", "delete_all_data", {}),
]

for name, tool, args in tests:
    r = check(tool, args)
    status = "BLOCKED" if r.blocked else ("PASS" if r.passed else "FAIL")
    cost = f"${r.estimated_cost:.0f}/mo" if r.estimated_cost else ""
    print(f"\n[{status}] {name}")
    print(f"  Safety: {r}")
    if r.errors:
        for e in r.errors:
            print(f"  ERROR: {e[:100]}")
