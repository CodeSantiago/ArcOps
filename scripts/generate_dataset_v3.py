#!/usr/bin/env python3
"""ArcOps dataset generator v3 — Clean, consistent, high-quality synthetic data.

Key improvements over v1/v2:
- DETERMINISTIC: same prompt always maps to same JSON (no random noise)
- CLEAN: no extra spaces, no inconsistent arguments, no conflicting examples
- REALISTIC: natural language patterns a real user would use
- FORMAT: ChatML with tool_calls in the format HuggingFace expects
"""

import json
import os
import random
from datetime import date, timedelta

SEED = 42
random.seed(SEED)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "training_dataset.jsonl")
TOOLS_PATH = os.path.join(ROOT, "src", "cloudops_fc", "schemas", "tool_definitions.json")

SYSTEM = (
    "You are a CloudOps infrastructure assistant. "
    "Output ONLY the JSON tool call. No explanations, no markdown."
)

# ── Constants ───────────────────────────────────────────────────────────

REGIONS = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "eu-west-1", "eu-central-1", "eu-west-2",
    "ap-southeast-1", "ap-southeast-2", "ap-northeast-1",
    "sa-east-1", "ca-central-1",
]

INSTANCE_TYPES = {
    "t3.micro":  ["small", "cheap", "tiny"],
    "t3.small":  ["small", "modest", "light"],
    "t3.medium": ["medium", "balanced", "standard"],
    "m5.large":  ["large", "big", "powerful"],
    "m5.xlarge": ["large", "big", "heavy"],
    "c6i.large": ["compute", "cpu-heavy", "processing"],
}

PORTS = [22, 80, 443, 8080, 3000, 5432, 6379]

DB_NAMES = [
    "prod-db-01", "staging-mysql", "analytics-postgres",
    "app-db-primary", "users-db", "inventory-mysql", "logs-postgres",
]

# ── Helpers ─────────────────────────────────────────────────────────────

tag_combos = [
    ({"Name": "web"}, "Name=web"),
    ({"Name": "api", "Env": "prod"}, "Name=api Env=prod"),
    ({"Name": "db", "Env": "staging"}, "Name=db Env=staging"),
    ({"Name": "worker", "Env": "dev"}, "Name=worker Env=dev"),
    ({"Name": "bastion"}, "Name=bastion"),
    ({"Name": "proxy", "Team": "platform"}, "Name=proxy Team=platform"),
]

def make_example(user_text, tool_name, arguments):
    """Create a dataset example in ChatML format with tool_calls."""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_text},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(
                        arguments, ensure_ascii=False, separators=(",", ":")
                    ),
                },
                    }
                ],
            },
        ]
    }

def ec2(instance_type, region, **extra):
    """Shorthand for EC2 tool call."""
    args = {"instance_type": instance_type, "region": region}
    args.update(extra)
    return make_example(None, "create_ec2_instance", args)

def rds(db_id, region, **extra):
    args = {"db_instance_identifier": db_id, "region": region}
    args.update(extra)
    return make_example(None, "restart_database", args)

def billing(**args):
    return make_example(None, "get_billing_alert", args)

# ── EC2 — Basic (3000) ─────────────────────────────────────────────────

ec2_basic_prompts = [
    "Create a {adj} {size} server in {region}",
    "Launch a {adj} {size} EC2 instance in {region}",
    "Spin up a {size} server in {region}",
    "I need a {size} instance in {region}",
    "Provision a {size} EC2 in {region}",
]

ec2_basic_examples = []
sizes_list = list(INSTANCE_TYPES.keys())
for _ in range(3000):
    size = random.choice(sizes_list)
    region = random.choice(REGIONS)
    tmpl = random.choice(ec2_basic_prompts)
    adj = random.choice(INSTANCE_TYPES[size]) if random.random() > 0.3 else ""
    prompt = tmpl.format(adj=adj, size=size, region=region).replace("  ", " ").strip()
    ex = ec2(size, region)
    ex["messages"][1]["content"] = prompt
    ec2_basic_examples.append(ex)

# ── EC2 — With ports (600) ─────────────────────────────────────────────

ec2_port_prompts = [
    "Create a {adj} {size} server in {region} with port {port} open",
    "Launch a {size} in {region} and open port {port}",
    "Deploy a {size} server in {region}, port {port} accessible",
]

ec2_port_examples = []
for _ in range(1000):
    size = random.choice(sizes_list)
    region = random.choice(REGIONS)
    port = random.choice(PORTS)
    tmpl = random.choice(ec2_port_prompts)
    adj = random.choice(INSTANCE_TYPES[size]) if random.random() > 0.3 else ""
    prompt = tmpl.format(adj=adj, size=size, region=region, port=port).replace("  ", " ").strip()
    sg = [{"port": port, "protocol": "tcp", "cidr": "0.0.0.0/0"}]
    ex = ec2(size, region, security_group_rules=sg)
    ex["messages"][1]["content"] = prompt
    ec2_port_examples.append(ex)

# ── EC2 — With tags (1000) ─────────────────────────────────────────────

ec2_tag_examples = []
for _ in range(1000):
    size = random.choice(sizes_list)
    region = random.choice(REGIONS)
    tags, tags_str = random.choice(tag_combos)
    prompt = f"Create a {size} server in {region} with tags {tags_str}"
    aws_tags = [{"key": k, "value": v} for k, v in tags.items()]
    ex = ec2(size, region, tags=aws_tags)
    ex["messages"][1]["content"] = prompt
    ec2_tag_examples.append(ex)

# ── EC2 — Ports + Tags ─────────────────────────────────────────────────

ec2_full_examples = []
for _ in range(800):
    size = random.choice(sizes_list)
    region = random.choice(REGIONS)
    port = random.choice(PORTS)
    tags, tags_str = random.choice(tag_combos)
    prompt = f"Create a {size} server in {region} with port {port} and tags {tags_str}"
    sg = [{"port": port, "protocol": "tcp", "cidr": "0.0.0.0/0"}]
    aws_tags = [{"key": k, "value": v} for k, v in tags.items()]
    ex = ec2(size, region, security_group_rules=sg, tags=aws_tags)
    ex["messages"][1]["content"] = prompt
    ec2_full_examples.append(ex)

# ── RDS — Basic (900) ──────────────────────────────────────────────────

rds_prompts = [
    "Restart the {db} database in {region}",
    "Reboot database {db} in {region}",
    "Restart {db} in {region}",
    "The {db} database is down, restart it in {region}",
]

rds_examples = []
for _ in range(2000):
    db = random.choice(DB_NAMES)
    region = random.choice(REGIONS)
    tmpl = random.choice(rds_prompts)
    prompt = tmpl.format(db=db, region=region)
    ex = rds(db, region)
    ex["messages"][1]["content"] = prompt
    rds_examples.append(ex)

# ── RDS — With failover (400) ──────────────────────────────────────────

rds_failover_prompts_yes = [
    "Restart {db} in {region} with failover",
    "Restart the {db} database and force a failover in {region}",
    "Reboot {db} in {region}, enable force failover",
]
rds_failover_prompts_no = [
    "Restart {db} in {region} without failover",
    "Restart {db} in {region} no failover",
    "Reboot {db} in {region} normally, no failover needed",
]

rds_failover_examples = []
for _ in range(200):
    db = random.choice(DB_NAMES)
    region = random.choice(REGIONS)
    tmpl = random.choice(rds_failover_prompts_yes)
    prompt = tmpl.format(db=db, region=region)
    ex = rds(db, region, force_failover=True)
    ex["messages"][1]["content"] = prompt
    rds_failover_examples.append(ex)

for _ in range(200):
    db = random.choice(DB_NAMES)
    region = random.choice(REGIONS)
    tmpl = random.choice(rds_failover_prompts_no)
    prompt = tmpl.format(db=db, region=region)
    ex = rds(db, region, force_failover=False)
    ex["messages"][1]["content"] = prompt
    rds_failover_examples.append(ex)

# ── Billing — Basic ────────────────────────────────────────────────────

billing_basic = [
    (
        "How much did we spend on AWS this month?",
        {
            "granularity": "MONTHLY",
            "time_period_end": "2026-07-24",
            "time_period_start": "2026-01-01",
        },
    ),
    (
        "What are our AWS costs for this month?",
        {
            "granularity": "MONTHLY",
            "time_period_end": "2026-07-24",
            "time_period_start": "2026-01-01",
        },
    ),
    (
        "Show me the AWS billing for the current month",
        {
            "granularity": "MONTHLY",
            "time_period_end": "2026-07-24",
            "time_period_start": "2026-01-01",
        },
    ),
    (
        "Get our AWS spending for this month",
        {
            "granularity": "MONTHLY",
            "time_period_end": "2026-07-24",
            "time_period_start": "2026-01-01",
        },
    ),
    (
        "Check AWS costs for the current billing period",
        {
            "granularity": "MONTHLY",
            "time_period_end": "2026-07-24",
            "time_period_start": "2026-01-01",
        },
    ),
    (
        "What did we spend on AWS this month?",
        {
            "granularity": "MONTHLY",
            "metrics": ["UnblendedCost"],
            "time_period_end": "2026-07-24",
            "time_period_start": "2026-01-01",
        },
    ),
    (
        "How much is our AWS bill?",
        {
            "granularity": "MONTHLY",
            "metrics": ["BlendedCost"],
            "time_period_end": "2026-07-24",
            "time_period_start": "2026-01-01",
        },
    ),
]

billing_service = [
    ("What did we spend on {svc} this month?",
     lambda s: {"granularity": "MONTHLY", "metrics": ["UnblendedCost"], "group_by_service": True,
                "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}),
    ("How much is {svc} costing us on AWS?",
     lambda s: {"granularity": "MONTHLY", "metrics": ["UnblendedCost"], "group_by_service": True,
                "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}),
    ("Show me the AWS costs for {svc}",
     lambda s: {"granularity": "MONTHLY", "metrics": ["UnblendedCost"], "group_by_service": True,
                "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}),
    ("Get the {svc} billing from AWS",
     lambda s: {"granularity": "MONTHLY", "metrics": ["UnblendedCost"], "group_by_service": True,
                "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}),
]

billing_examples = []
for prompt, args in billing_basic:
    for _ in range(60):  # Repeat each pattern multiple times
        ex = billing(**args)
        ex["messages"][1]["content"] = prompt
        billing_examples.append(ex)

services = ["EC2", "RDS", "S3", "Lambda", "ECS", "ElastiCache", "CloudFront"]
for tmpl, fn in billing_service:
    for svc in services:
        for _ in range(25):
            prompt = tmpl.format(svc=svc)
            ex = billing(**fn(svc))
            ex["messages"][1]["content"] = prompt
            billing_examples.append(ex)

# ── NOISE EXAMPLES (instructions with irrelevant info) ──────────────────
# The model must learn to IGNORE extra text that doesn't map to parameters

noise_ec2 = [
    "also make sure it's secure",
    "and notify me when it's done",
    "please log everything",
    "and send an alert to the team",
    "ASAP, this is urgent",
    "thanks!",
    "and add monitoring",
    "make sure to enable backups",
    "remember to tag it properly",
]
noise_rds = [
    "but first check if it's healthy",
    "and let me know when it's back up",
    "but also log the event",
    "and notify the on-call engineer",
    "make sure to snapshot first",
    "please confirm before executing",
]

noise_examples = []
for size in random.sample(sizes_list, 3):
    for region in random.sample(REGIONS, 2):
        noise = random.choice(noise_ec2)
        prompt = f"Create a {size} server in {region}, {noise}"
        ex = ec2(size, region)
        ex["messages"][1]["content"] = prompt
        noise_examples.append(ex)

        port = random.choice(PORTS)
        noise = random.choice(noise_ec2)
        prompt = f"Launch a {size} in {region} with port {port} open, {noise}"
        sg = [{"port": port, "protocol": "tcp", "cidr": "0.0.0.0/0"}]
        ex = ec2(size, region, security_group_rules=sg)
        ex["messages"][1]["content"] = prompt
        noise_examples.append(ex)

for db in random.sample(DB_NAMES, 4):
    for region in random.sample(REGIONS, 2):
        noise = random.choice(noise_rds)
        prompt = f"Restart {db} in {region}, {noise}"
        ex = rds(db, region)
        ex["messages"][1]["content"] = prompt
        noise_examples.append(ex)

        noise = random.choice(noise_rds)
        prompt = f"Restart {db} in {region} with failover, {noise}"
        ex = rds(db, region, force_failover=True)
        ex["messages"][1]["content"] = prompt
        noise_examples.append(ex)

# ── Daily billing ──────────────────────────────────────────────────────

for _ in range(300):
    start = date(2026, 7, 1) + timedelta(days=random.randint(0, 20))
    end = start + timedelta(days=random.choice([7, 14, 30]))
    args = {
        "granularity": "DAILY",
        "time_period_start": start.isoformat(),
        "time_period_end": end.isoformat(),
        "metrics": ["UnblendedCost"],
    }
    prompt = f"Show me daily AWS costs from {start} to {end}"
    ex = billing(**args)
    ex["messages"][1]["content"] = prompt
    billing_examples.append(ex)

# ── WEAK FIELD BOOSTERS ──────────────────────────────────────────────
# Targeted examples for fields that score low in eval

# 1. security_group_rules (0%) — 400 dedicated examples (mixed single and multi-rule)
sg_examples = []
sg_prompts_single = [
    "Create a {size} server in {region} allowing port {port}",
    "Launch a {size} instance in {region} with port {port} accessible",
    "Deploy a {size} EC2 in {region} and open port {port}",
    "I need a {size} server in {region} with port {port} open",
]
sg_prompts_multi = [
    "Create a {size} server in {region} with ports {p1} and {p2} open",
    "Launch a {size} instance in {region} opening ports {p1}, {p2}",
    "Deploy a {size} EC2 in {region} with port {p1} and port {p2} accessible",
]
for _ in range(200):
    size = random.choice(sizes_list)
    region = random.choice(REGIONS)
    port = random.choice(PORTS)
    tmpl = random.choice(sg_prompts_single)
    prompt = tmpl.format(size=size, region=region, port=port)
    sg = [{"port": port, "protocol": "tcp", "cidr": "0.0.0.0/0"}]
    ex = ec2(size, region, security_group_rules=sg)
    ex["messages"][1]["content"] = prompt
    sg_examples.append(ex)
for _ in range(350):
    size = random.choice(sizes_list)
    region = random.choice(REGIONS)
    p1, p2 = random.sample(PORTS, 2)
    tmpl = random.choice(sg_prompts_multi)
    prompt = tmpl.format(size=size, region=region, p1=p1, p2=p2)
    sg = [{"port": p1, "protocol": "tcp", "cidr": "0.0.0.0/0"},
          {"port": p2, "protocol": "tcp", "cidr": "0.0.0.0/0"}]
    ex = ec2(size, region, security_group_rules=sg)
    ex["messages"][1]["content"] = prompt
    sg_examples.append(ex)

# 2. billing metrics (0%) — 500 dedicated examples, ~20% multi-item
metrics_examples = []
metric_prompts = []
all_metrics = ["BlendedCost", "UnblendedCost", "UsageQuantity", "AmortizedCost", "NetUnblendedCost"]
# Single-metric (80%)
for m in all_metrics:
    for prompt_tmpl in [
        f"What is our {m} this month?",
        f"Get the {m} for this billing period",
        f"Show me AWS {m} this month",
    ]:
        for _ in range(10):
            args = {"granularity": "MONTHLY", "metrics": [m],
                    "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}
            ex = billing(**args)
            ex["messages"][1]["content"] = prompt_tmpl
            metrics_examples.append(ex)
# Multi-metric (20%) — lengths 2, 3, 4 with diverse combinations
multi_prompts = [
    "Show me {names} for this month",
    "I need {names} broken down for this period",
    "Give me the AWS {names} for this billing cycle",
]
for length in [2, 3, 4]:
    for _ in range(50):
        ms = random.sample(all_metrics, min(length, len(all_metrics)))
        connector = " and " if len(ms) == 2 else ", ".join(ms[:-1]) + ", and " + ms[-1]
        names = " and ".join(ms) if len(ms) <= 2 else ", ".join(ms[:-1]) + f", and {ms[-1]}"
        tmpl = random.choice(multi_prompts)
        prompt = tmpl.format(names=names)
        args = {"granularity": "MONTHLY", "metrics": ms,
                "time_period_end": "2026-07-24", "time_period_start": "2026-01-01"}
        ex = billing(**args)
        ex["messages"][1]["content"] = prompt
        metrics_examples.append(ex)

# 3. granularity (38%) — clear DAILY vs MONTHLY cues
gran_examples = []
for _ in range(100):
    start = date(2026, 7, 1) + timedelta(days=random.randint(0, 20))
    end = start + timedelta(days=random.choice([7, 14, 30]))
    args = {"granularity": "DAILY", "metrics": ["UnblendedCost"],
            "time_period_start": start.isoformat(), "time_period_end": end.isoformat()}
    examples_list = [
        f"Show daily costs from {start} to {end}",
        f"I need a day-by-day breakdown from {start} to {end}",
        f"Give me the daily AWS spend between {start} and {end}",
    ]
    for p in examples_list:
        ex = billing(**args)
        ex["messages"][1]["content"] = p
        gran_examples.append(ex)

# 4. force_failover (44%) — balanced True/False examples
failover_examples = []
for db in DB_NAMES:
    for region in REGIONS[:4]:
        p_yes = f"Restart {db} in {region} with failover"
        ex = rds(db, region, force_failover=True)
        ex["messages"][1]["content"] = p_yes
        failover_examples.append(ex)
        p_no = f"Restart {db} in {region} without failover"
        ex = rds(db, region, force_failover=False)
        ex["messages"][1]["content"] = p_no
        failover_examples.append(ex)

# ── DEFAULT-VALUE EXAMPLES (400) ────────────────────────────────────────
# Fixes the biggest challenge failure: prompts with no size and/or no region.
# Model must learn defaults: instance_type=t3.micro, region=us-east-1.
default_ec2_prompts = [
    "I need a server",
    "Just a server please",
    "Give me a machine",
    "Launch a default server",
    "Set up a basic server",
    "Create an instance for me",
    "I need a virtual machine",
    "Give me a standard server",
]
default_rds_prompts = [
    "Restart the database",
    "Reboot the db",
    "Restart the primary database",
    "The database is down, restart it",
    "Reboot the main database",
]
default_examples = []
for _ in range(200):
    tmpl = random.choice(default_ec2_prompts)
    ex = ec2("t3.micro", "us-east-1")
    ex["messages"][1]["content"] = tmpl
    default_examples.append(ex)
for _ in range(200):
    tmpl = random.choice(default_rds_prompts)
    ex = rds("main-db", "us-east-1")
    ex["messages"][1]["content"] = tmpl
    default_examples.append(ex)

# ── CITY→REGION ALIAS EXAMPLES (300) ────────────────────────────────────
# Fixes the second failure: city names must map to region codes.
# Regions chosen are from the 12-region schema enum and NOT covered by any
# challenge-set city: us-west-1, us-west-2, ap-southeast-2.
CITY_MAP = {
    "California": "us-west-1",
    "San Francisco": "us-west-1",
    "Los Angeles": "us-west-1",
    "Oregon": "us-west-2",
    "Seattle": "us-west-2",
    "Portland": "us-west-2",
    "Sydney": "ap-southeast-2",
    "Melbourne": "ap-southeast-2",
}
city_examples = []
city_prompts = [
    "Create a {size} server in {city}",
    "Launch a {size} instance in {city}",
    "Spin up a {size} in {city}",
    "I need a {size} server in {city}",
    "Restart the database in {city}",
]
for city, region in CITY_MAP.items():
    for size in ["t3.micro", "t3.medium", "m5.large"]:
        prompt = random.choice(city_prompts).format(size=size, city=city)
        ex = ec2(size, region)
        ex["messages"][1]["content"] = prompt
        city_examples.append(ex)
    prompt = f"Restart the database in {city}"
    ex = rds("main-db", region)
    ex["messages"][1]["content"] = prompt
    city_examples.append(ex)

# ── RELATIVE-TIME BILLING EXAMPLES (300) ────────────────────────────────
# Fixes the third failure: relative time expressions must map to date ranges.
# TODAY is fixed at 2026-07-24 in the generator, so ranges are deterministic.
TODAY = date(2026, 7, 24)
relative_examples = []
rel_daily = [
    ("this week", TODAY - timedelta(days=6), TODAY),
    ("past 7 days", TODAY - timedelta(days=6), TODAY),
    ("past 30 days", TODAY - timedelta(days=29), TODAY),
    ("last 2 weeks", TODAY - timedelta(days=13), TODAY),
]
rel_monthly = [
    ("this quarter", date(2026, 7, 1), date(2026, 7, 24)),
    ("3 months ago", date(2026, 4, 1), date(2026, 4, 30)),
    ("past 3 months", date(2026, 4, 25), date(2026, 7, 24)),
    ("last 6 months", date(2026, 1, 25), date(2026, 7, 24)),
]
for label, start, end in rel_daily:
    for svc in ["EC2", "RDS", "S3", "Lambda"]:
        for _ in range(6):
            prompt = f"Show me daily {svc} costs for {label}"
            ex = billing(granularity="DAILY", metrics=["UnblendedCost"],
                         time_period_start=start.isoformat(), time_period_end=end.isoformat(),
                         group_by_service=True)
            ex["messages"][1]["content"] = prompt
            relative_examples.append(ex)
for label, start, end in rel_monthly:
    for svc in ["EC2", "RDS", "S3", "Lambda"]:
        for _ in range(8):
            prompt = f"What did we spend on {svc} {label}?"
            ex = billing(granularity="MONTHLY", metrics=["UnblendedCost"],
                         time_period_start=start.isoformat(), time_period_end=end.isoformat(),
                         group_by_service=True)
            ex["messages"][1]["content"] = prompt
            relative_examples.append(ex)

# ── Assemble ────────────────────────────────────────────────────────────

all_examples = (
    ec2_basic_examples
    + ec2_port_examples
    + ec2_tag_examples
    + ec2_full_examples
    + rds_examples
    + rds_failover_examples
    + billing_examples
    + sg_examples
    + metrics_examples
    + gran_examples
    + failover_examples
    + noise_examples
    + default_examples
    + city_examples
    + relative_examples
)

random.shuffle(all_examples)

# Ensure no None prompts
for ex in all_examples:
    if ex["messages"][1]["content"] is None:
        print("ERROR: None prompt found, skipping")
        all_examples.remove(ex)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    for ex in all_examples:
        f.write(json.dumps(ex, ensure_ascii=False) + "\n")

# ── Verify ──────────────────────────────────────────────────────────────
ec2_count = sum(1 for e in all_examples
    if any(tc["function"]["name"] == "create_ec2_instance"
           for m in e["messages"] if m.get("tool_calls")
           for tc in m["tool_calls"]))
rds_count = sum(1 for e in all_examples
    if any(tc["function"]["name"] == "restart_database"
           for m in e["messages"] if m.get("tool_calls")
           for tc in m["tool_calls"]))
bil_count = sum(1 for e in all_examples
    if any(tc["function"]["name"] == "get_billing_alert"
           for m in e["messages"] if m.get("tool_calls")
           for tc in m["tool_calls"]))

# Verify all examples have valid JSON tool_calls
invalid = 0
for ex in all_examples:
    try:
        for m in ex["messages"]:
            if m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    json.loads(tc["function"]["arguments"])
    except (json.JSONDecodeError, TypeError, KeyError):
        invalid += 1

print(f"Generated {len(all_examples)} examples")
print(f"  create_ec2_instance: {ec2_count}")
print(f"  restart_database:    {rds_count}")
print(f"  get_billing_alert:   {bil_count}")
if invalid:
    print(f"  INVALID JSON: {invalid}")
else:
    print("  All JSON valid: OK")
print(f"Output: {OUT}")
