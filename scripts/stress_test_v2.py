#!/usr/bin/env python3
"""ArcOps stress test v2 — more edge cases."""
import json, subprocess, socket, time, sys, os
from pathlib import Path

HOME = Path.home() / "fine_tuning_model"
CACHE = Path.home() / ".arcops" / "server.port"
LOCAL = "http://localhost:4566"
ENV = {**os.environ, "AWS_ACCESS_KEY_ID": "fake", "AWS_SECRET_ACCESS_KEY": "fake"}
AWS_BIN = str(HOME / ".venv" / "bin" / "aws")
AWS = [AWS_BIN, "--endpoint-url", LOCAL, "--region", "us-east-1"]

P, F = 0, 0
ERR = []

def log(name, ok, detail=""):
    global P, F
    if ok: P += 1
    else: F += 1; ERR.append(f"{name}: {detail[:150]}")
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

def aws(args):
    try:
        r = subprocess.run(AWS + args, capture_output=True, text=True, timeout=15, env=ENV, cwd=HOME)
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
        return {"_err": r.stderr[:150]}
    except Exception as e: return {"_err": str(e)}

def model(prompt):
    if not CACHE.exists(): return {"error": "No server"}
    try:
        s = socket.create_connection(("127.0.0.1", int(CACHE.read_text())), timeout=120)
        s.send(json.dumps({"prompt": prompt}).encode())
        d = s.recv(65536).decode(); s.close()
        return json.loads(d)
    except Exception as e: return {"error": str(e)}

def safety_blocked(name, args):
    schemas = {
        "create_ec2_instance": {"allowed":{"region","instance_type","security_group_rules","tags"}},
        "restart_database": {"allowed":{"db_instance_identifier","region","force_failover"}},
        "get_billing_alert": {"allowed":{"time_period_start","time_period_end","granularity","metrics","group_by_service"}},
    }
    s = schemas.get(name)
    if not s: return True
    for k in args:
        if k not in s["allowed"]: return True
    return False

def describe(iid):
    r = aws(["ec2","describe-instances","--instance-ids",iid])
    if r and "Instances" in r:
        return r["Instances"][0] if r["Instances"] else None
    return None

print("\n═══  MODEL INFERENCE ═══\n")

# Edge: Instance types that don't exist
prompts = [
    ("c6i.4xlarge", "Create a c6i.4xlarge server in eu-central-1"),
    ("t3.nano", "Create a t3.nano instance in ap-southeast-1"),
    ("r5.2xlarge", "Create a r5.2xlarge server in us-west-2"),
]
test_instances = []
for etype, prompt in prompts:
    r = model(prompt)
    ok = r.get("arguments",{}).get("instance_type") == etype
    log(f"Instance type: {etype}", ok, str(r)[:100])
    if ok:
        # Actually create it
        ri = aws(["ec2","run-instances","--instance-type",etype])
        if ri and "Instances" in ri:
            iid = ri["Instances"][0].get("InstanceId","")
            if iid: test_instances.append(iid)

# Edge: Regions that exist
for region in ["eu-west-1", "ap-southeast-1", "sa-east-1", "ca-central-1"]:
    r = model(f"Create a t3.micro server in {region}")
    log(f"Region: {region}", r.get("arguments",{}).get("region") == region, str(r)[:80])

# Edge: Regions that don't exist (model should use closest)
r = model("Create a server in Sydney")
log("City: Sydney → ap-southeast-2", r.get("arguments",{}).get("region") == "ap-southeast-2", str(r)[:80])
r = model("Create a server in London")
log("City: London → eu-west-2", r.get("arguments",{}).get("region") == "eu-west-2", str(r)[:80])

# Edge: Ambiguous prompts
r = model("Restart the database")
log("Ambiguous 'restart database'", r.get("name") == "restart_database", str(r)[:80])

r = model("I need a server")
log("Ambiguous 'I need a server'", r.get("name") == "create_ec2_instance", str(r)[:80])

# Edge: Very short prompts
for p in ["Server", "EC2", "RDS", "Billing", "Create", "Restart"]:
    r = model(p)
    log(f"Short prompt: '{p}'", "error" not in r and "name" in r, str(r)[:80])

# Edge: Very long instance type
r = model("Create a this-is-not-a-real-instance-type server in us-east-1")
log("Fake instance type", r.get("arguments",{}).get("instance_type","").startswith("this") == False, str(r)[:80])

# Edge: Mixed languages
r = model("Create un server t3.medium en Virginia con puerto 443")
log("Spanglish prompt", r.get("name") == "create_ec2_instance", str(r)[:80])

# Edge: Numbers as strings
r = model("Open port twenty two on my server in us-east-1")
args = r.get("arguments",{})
sg = args.get("security_group_rules",[])
log("Port as word 'twenty two'", sg and sg[0].get("port","") != "twenty two", str(r)[:80])

# Edge: Extremely detailed prompt
r = model("Create a m5.xlarge server in us-west-2 with ports 22, 80, 443, 8080, 3000, 5432, 6379 open and tags Name=production-web, Env=prod, Team=infrastructure, CostCenter=cc-123, Project=arcops")
args = r.get("arguments",{})
sg = args.get("security_group_rules",[])
tags = args.get("tags",[])
log("7 ports in prompt", len(sg) >= 5, f"got {len(sg)}")
log("5 tags in prompt", len(tags) == 5, f"got {len(tags)}")
log("Correct instance type", args.get("instance_type") == "m5.xlarge", str(r)[:80])

print("\n═══  SAFETY LAYER ═══\n")

# Test all known hallucinated params
hallucinations = ["log_event", "notify", "send_email", "callback_url", "webhook", "alert", "priority", "environment", "owner", "created_by"]
for h in hallucinations:
    r = model(f"Restart prod-db database in us-east-1, {h}=true")
    blocked = h not in r.get("arguments",{})
    log(f"Safety blocks '{h}'", blocked, str(r)[:80])

# Test safety layer directly
safety_tests = [
    ("Valid EC2", "create_ec2_instance", {"region":"us-east-1","instance_type":"t3.micro"}, False),
    ("Hallucinated param", "restart_database", {"db_instance_identifier":"x","region":"us-east-1","log_event":True}, True),
    ("Extra param", "create_ec2_instance", {"region":"us-east-1","instance_type":"t3.micro","color":"red"}, True),
    ("No required", "restart_database", {"force_failover":True}, True),
    ("Empty args EC2", "create_ec2_instance", {}, False),  # no required, but not blocked
    ("Unknown tool", "delete_everything", {}, True),
    ("Billing empty", "get_billing_alert", {}, False),
    ("Mix valid + invalid", "create_ec2_instance", {"region":"us-east-1","instance_type":"t3.micro","something":"x"}, True),
]
for name, tool, args, expects_block in safety_tests:
    r = safety_blocked(tool, args)
    log(f"Safety: {name}", r == expects_block, f"expected_block={expects_block} got={r}")

print("\n═══  AWS OPERATIONS ═══\n")

# Create with various params
created = []
variants = [
    ("default", ["ec2","run-instances","--instance-type","t3.micro"]),
    ("m5.large", ["ec2","run-instances","--instance-type","m5.large"]),
    ("c6i.large", ["ec2","run-instances","--instance-type","c6i.large"]),
]
for name, cmd in variants:
    r = aws(cmd)
    iid = r.get("Instances",[{}])[0].get("InstanceId","") if isinstance(r,dict) else ""
    log(f"Create {name}", bool(iid), str(r)[:100])
    if iid: created.append(iid)

# Start/stop/terminate each
for iid in created:
    # Stop
    aws(["ec2","stop-instances","--instance-ids",iid])
    time.sleep(0.5)
    inst = describe(iid)
    stopped = inst and inst.get("State",{}).get("Name") in ("stopped","stopping")
    log(f"Stop {iid}", stopped, str(inst.get("State",{})) if inst else "")

    # Start
    aws(["ec2","start-instances","--instance-ids",iid])
    time.sleep(0.5)
    inst = describe(iid)
    started = inst and inst.get("State",{}).get("Name") in ("running","pending")
    log(f"Start {iid}", started, str(inst.get("State",{})) if inst else "")

    # Tag
    aws(["ec2","create-tags","--resources",iid,"--tags","Key=Name,Value=stress-test","Key=Env,Value=testing"])
    inst = describe(iid)
    if inst:
        tags = {t["Key"]:t["Value"] for t in inst.get("Tags",[])}
        log(f"Tag {iid} (2 tags)", tags.get("Name") == "stress-test" and tags.get("Env") == "testing", str(tags))

    # Tag update (overwrite)
    # First delete old tags
    if inst:
        for t in inst.get("Tags",[]):
            aws(["ec2","delete-tags","--resources",iid,"--tags",f"Key={t['Key']}"])
    aws(["ec2","create-tags","--resources",iid,"--tags","Key=Name,Value=updated"])
    inst = describe(iid)
    if inst:
        tags = {t["Key"]:t["Value"] for t in inst.get("Tags",[])}
        log(f"Tag overwrite {iid}", tags.get("Name") == "updated" and "Env" not in tags, str(tags))

    # Terminate
    aws(["ec2","terminate-instances","--instance-ids",iid])
    inst = describe(iid)
    terminated = inst and inst.get("State",{}).get("Name") in ("terminated","shutting-down")
    log(f"Terminate {iid}", terminated, str(inst.get("State",{})) if inst else "")

# Cleanup any remaining
for iid in test_instances:
    aws(["ec2","terminate-instances","--instance-ids",iid])

print("\n═══  TUI FLOW ═══\n")

# Test the arcops CLI works
for p in ["Create a t3.micro server in us-east-1", "How much did we spend?"]:
    r = subprocess.run([str(HOME/".venv/bin/python"), "cloudops.py", "--json", p],
                      capture_output=True, text=True, timeout=120, cwd=HOME,
                      env={**ENV, "HOME": str(Path.home())})
    try:
        d = json.loads(r.stdout.strip())
        log(f"CLI works: {p[:40]}", "name" in d and "arguments" in d, r.stdout.strip()[:80])
    except:
        log(f"CLI works: {p[:40]}", False, r.stdout.strip()[:80] or r.stderr.strip()[:80])

# Test --json flag output is parseable
r = subprocess.run([str(HOME/".venv/bin/python"), "cloudops.py", "--json", "Create a server with tags Name=test"],
                  capture_output=True, text=True, timeout=120, cwd=HOME,
                  env={**ENV, "HOME": str(Path.home())})
try:
    json.loads(r.stdout.strip())
    log("CLI --json valid JSON", True)
except:
    log("CLI --json valid JSON", False, r.stdout.strip()[:100])

print("\n═══  CONCURRENT OPERATIONS ═══\n")

# Create 3 instances rapidly, verify all exist
iids = []
for i in range(3):
    r = aws(["ec2","run-instances","--instance-type","t3.micro"])
    iid = r.get("Instances",[{}])[0].get("InstanceId","") if isinstance(r,dict) else ""
    if iid: iids.append(iid)
    time.sleep(0.3)
log(f"Create 3 concurrent EC2", len(iids) == 3, str(iids))

# Verify all exist
if iids:
    for iid in iids:
        inst = describe(iid)
        exists = inst is not None
        log(f"  Verify {iid} exists", exists, str(inst.get("State",{}).get("Name")) if inst else "")

# Delete all
for iid in iids:
    aws(["ec2","terminate-instances","--instance-ids",iid])

print("\n═══  CONFIG VALIDATION ═══\n")

# Check all config files exist
files = [
    "app/tui.py",
    "app/safety.py",
    "cloudops.py",
    "scripts/training/train.py",
    "scripts/generate_dataset_v3.py",
    "scripts/training/default_config.yaml",
    "scripts/training/config_1.5b.yaml",
]
for f in files:
    exists = (HOME / f).exists()
    log(f"Config file: {f}", exists)

# Check model server is running
r = CACHE.exists() and int(CACHE.read_text())
sock = None
try:
    sock = socket.create_connection(("127.0.0.1", r), timeout=2)
    sock.close()
    log("Model server running", True)
except:
    log("Model server running", False)

# Check training adapter exists
adapter = HOME / "checkpoints" / "final" / "adapter_config.json"
log("Training adapter exists", adapter.exists())

# Check dataset exists
ds = HOME / "data" / "training_dataset.jsonl"
if ds.exists():
    import json as j
    lines = sum(1 for _ in open(ds))
    log(f"Dataset exists ({lines} examples)", lines > 1000, f"{lines} lines")
else:
    log("Dataset exists", False)

# ═══════════════════════════════════════════════
print(f"\n{'='*50}")
print(f"  TOTAL: {P} PASS, {F} FAIL")
if ERR:
    print(f"\n  Failures:")
    for e in ERR[:10]:
        print(f"    - {e}")
    if len(ERR) > 10:
        print(f"    ... and {len(ERR)-10} more")
print(f"{'='*50}")
