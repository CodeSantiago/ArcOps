#!/usr/bin/env python3
"""Generate a CLEAN, consistent dataset for ArcOps fine-tuning.
Quality over quantity: 3000 curated examples, no random noise."""
import json, os, random

SEED = 42
random.seed(SEED)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = json.load(open(os.path.join(ROOT, "src", "cloudops_fc", "schemas", "tool_definitions.json")))
OUT = os.path.join(ROOT, "data", "dataset_v2.jsonl")

SYSTEM = "You are a CloudOps infrastructure assistant. Output ONLY the JSON tool call. No explanations, no markdown."

def make(role, content, tool_calls=None):
    m = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]
    if tool_calls:
        m.append({"role": "assistant", "content": None, "tool_calls": [{
            "type": "function", "function": {
                "name": tool_calls["name"],
                "arguments": json.dumps(tool_calls["arguments"], ensure_ascii=False)
            }
        }]})
    else:
        m.append({"role": "assistant", "content": "{}"})
    return {"messages": m}

examples = []

# ── create_ec2_instance (1200 examples) ──────────────────────────────────

# Templates that always map to the SAME JSON (deterministic)
ec2_templates = [
    # (prompt_template, args_template)
    # Each template fills in parameters consistently
    ("Create a {size} server in {region}", lambda s,r: {"region": r, "instance_type": s}),
    ("Launch a {size} EC2 instance in {region}", lambda s,r: {"region": r, "instance_type": s}),
    ("Spin up a {size} in {region}", lambda s,r: {"region": r, "instance_type": s}),
    ("Provision a {size} virtual machine in {region}", lambda s,r: {"region": r, "instance_type": s}),
    ("I need a {size} server in {region}", lambda s,r: {"region": r, "instance_type": s}),
    ("Deploy a {size} instance in the {region} region", lambda s,r: {"region": r, "instance_type": s}),
    ("Start a {size} in {region} for me", lambda s,r: {"region": r, "instance_type": s}),
]

# With ports
ec2_port_templates = [
    ("Create a {size} in {region} with port {port} open", lambda s,r,p: {"region": r, "instance_type": s, "security_group_rules": [{"port": p, "protocol": "tcp", "cidr": "0.0.0.0/0"}]}),
    ("Launch a {size} server in {region} opening port {port}", lambda s,r,p: {"region": r, "instance_type": s, "security_group_rules": [{"port": p, "protocol": "tcp", "cidr": "0.0.0.0/0"}]}),
    ("Set up a {size} in {region} with port {port} accessible", lambda s,r,p: {"region": r, "instance_type": s, "security_group_rules": [{"port": p, "protocol": "tcp", "cidr": "0.0.0.0/0"}]}),
]

# With tags
ec2_tag_templates = [
    ("Create a {size} in {region} with tags {tags}", lambda s,r,t: dict({"region": r, "instance_type": s}, **t)),
]

# With ports + tags
ec2_full_templates = [
    ("Create a {size} in {region} port {port} open tags {tags}", lambda s,r,p,tt: dict({"region": r, "instance_type": s, "security_group_rules": [{"port": p, "protocol": "tcp", "cidr": "0.0.0.0/0"}]}, **tt)),
]

sizes = ["t3.micro", "t3.small", "t3.medium", "m5.large", "m5.xlarge", "c6i.large", "t2.micro", "t3.nano"]
regions = ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "eu-west-1", "eu-central-1", "ap-southeast-1", "sa-east-1"]
ports = [22, 80, 443, 8080, 3000, 5432, 6379, 27017]
tag_sets = [
    {},  # no tags
    {"tags": [{"key": "Name", "value": "web"}]},
    {"tags": [{"key": "Name", "value": "api"}, {"key": "Env", "value": "prod"}]},
    {"tags": [{"key": "Name", "value": "db"}, {"key": "Env", "value": "staging"}]},
]

for _ in range(600):
    s = random.choice(sizes)
    r = random.choice(regions)
    tmpl, fn = random.choice(ec2_templates)
    prompt = tmpl.format(size=s, region=r)
    args = fn(s, r)
    examples.append(make("user", prompt, {"name": "create_ec2_instance", "arguments": args}))

for _ in range(300):
    s = random.choice(sizes)
    r = random.choice(regions)
    p = random.choice(ports)
    tmpl, fn = random.choice(ec2_port_templates)
    prompt = tmpl.format(size=s, region=r, port=p)
    args = fn(s, r, p)
    examples.append(make("user", prompt, {"name": "create_ec2_instance", "arguments": args}))

for _ in range(200):
    s = random.choice(sizes)
    r = random.choice(regions)
    t = random.choice(tag_sets)
    tmpl, fn = random.choice(ec2_tag_templates)
    tags_str = " ".join(f"{x['key']}={x['value']}" for x in t.get("tags", []))
    prompt = tmpl.format(size=s, region=r, tags=tags_str or "none")
    args = fn(s, r, t)
    examples.append(make("user", prompt, {"name": "create_ec2_instance", "arguments": args}))

for _ in range(100):
    s = random.choice(sizes)
    r = random.choice(regions)
    p = random.choice(ports)
    t = random.choice(tag_sets)
    tmpl, fn = random.choice(ec2_full_templates)
    tags_str = " ".join(f"{x['key']}={x['value']}" for x in t.get("tags", []))
    prompt = tmpl.format(size=s, region=r, port=p, tags=tags_str or "none")
    args = fn(s, r, p, t)
    examples.append(make("user", prompt, {"name": "create_ec2_instance", "arguments": args}))

# ── restart_database (800 examples) ─────────────────────────────────────

db_templates = [
    ("Restart the {name} database in {region}", lambda n,r: {"db_instance_identifier": n, "region": r}),
    ("Reboot the {name} database in {region}", lambda n,r: {"db_instance_identifier": n, "region": r}),
    ("Restart the database {name} in {region}", lambda n,r: {"db_instance_identifier": n, "region": r}),
    ("The {name} database is down, restart it in {region}", lambda n,r: {"db_instance_identifier": n, "region": r}),
    ("Reboot database {name} located in {region}", lambda n,r: {"db_instance_identifier": n, "region": r}),
    ("Perform a restart of {name} in {region}", lambda n,r: {"db_instance_identifier": n, "region": r}),
    ("Restart {name} which is in {region}", lambda n,r: {"db_instance_identifier": n, "region": r}),
]

db_failover_templates = [
    ("Restart the {name} database in {region} with failover", lambda n,r: {"db_instance_identifier": n, "region": r, "force_failover": True}),
    ("Restart {name} in {region} and force a failover", lambda n,r: {"db_instance_identifier": n, "region": r, "force_failover": True}),
    ("Reboot {name} in {region} with force failover enabled", lambda n,r: {"db_instance_identifier": n, "region": r, "force_failover": True}),
]

db_names = ["prod-db-01", "staging-mysql", "analytics-postgres", "app-db-primary", "users-db", "inventory-mysql", "logs-postgres"]

for _ in range(500):
    n = random.choice(db_names)
    r = random.choice(regions)
    tmpl, fn = random.choice(db_templates)
    prompt = tmpl.format(name=n, region=r)
    args = fn(n, r)
    examples.append(make("user", prompt, {"name": "restart_database", "arguments": args}))

for _ in range(300):
    n = random.choice(db_names)
    r = random.choice(regions)
    tmpl, fn = random.choice(db_failover_templates)
    prompt = tmpl.format(name=n, region=r)
    args = fn(n, r)
    examples.append(make("user", prompt, {"name": "restart_database", "arguments": args}))

# ── get_billing_alert (600 examples) ─────────────────────────────────────

billing_templates = [
    ("How much did we spend on AWS this month?", lambda: {"granularity": "MONTHLY", "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}),
    ("What are our AWS costs for this month?", lambda: {"granularity": "MONTHLY", "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}),
    ("Show me the AWS billing for this month", lambda: {"granularity": "MONTHLY", "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}),
    ("Get my AWS spending for the current month", lambda: {"granularity": "MONTHLY", "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}),
    ("How much AWS credit did we use?", lambda: {"granularity": "MONTHLY", "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}),
    ("Check our AWS billing", lambda: {"granularity": "MONTHLY", "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}),
    ("What did we spend on AWS?", lambda: {"granularity": "MONTHLY", "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}),
]

billing_service_templates = [
    ("What did we spend on {service} this month?", lambda s: {"granularity": "MONTHLY", "group_by_service": True, "time_period_end": "2026-07-24", "time_period_start": "2026-01-01", "metrics": ["UnblendedCost"]}),
    ("Show me the AWS costs for {service}", lambda s: {"granularity": "MONTHLY", "group_by_service": True, "time_period_end": "2026-07-24", "time_period_start": "2026-01-01", "metrics": ["UnblendedCost"]}),
    ("How much is {service} costing us?", lambda s: {"granularity": "MONTHLY", "group_by_service": True, "time_period_end": "2026-07-24", "time_period_start": "2026-01-01", "metrics": ["UnblendedCost"]}),
]

services = ["EC2", "RDS", "S3", "Lambda", "ECS", "ElastiCache"]

for _ in range(300):
    tmpl, fn = random.choice(billing_templates)
    prompt = tmpl()
    args = fn()
    examples.append(make("user", prompt, {"name": "get_billing_alert", "arguments": args}))

for _ in range(300):
    s = random.choice(services)
    tmpl, fn = random.choice(billing_service_templates)
    prompt = tmpl(service=s)
    args = fn(s)
    examples.append(make("user", prompt, {"name": "get_billing_alert", "arguments": args}))

# ── Shuffle and write ─────────────────────────────────────────────────────

random.shuffle(examples)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    for ex in examples:
        f.write(json.dumps(ex, ensure_ascii=False) + "\n")

print(f"Generated {len(examples)} examples")
print(f"Output: {OUT}")
print(f"  create_ec2_instance: {sum(1 for e in examples if any(m.get('tool_calls',[{}])[0].get('function',{}).get('name')=='create_ec2_instance' for m in e['messages'] if 'tool_calls' in m))}")
print(f"  restart_database:     {sum(1 for e in examples if any(m.get('tool_calls',[{}])[0].get('function',{}).get('name')=='restart_database' for m in e['messages'] if 'tool_calls' in m))}")
print(f"  get_billing_alert:    {sum(1 for e in examples if any(m.get('tool_calls',[{}])[0].get('function',{}).get('name')=='get_billing_alert' for m in e['messages'] if 'tool_calls' in m))}")
