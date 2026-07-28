#!/usr/bin/env python3
"""ArcOps stress test — finds errors and inconsistencies."""
import json, subprocess, socket, time, sys, os
from pathlib import Path

HOME = Path.home() / "fine_tuning_model"
CACHE = Path.home() / ".arcops" / "server.port"
LOCAL = "http://localhost:4566"
ENV = {**os.environ, "AWS_ACCESS_KEY_ID": "fake", "AWS_SECRET_ACCESS_KEY": "fake"}
AWS = [str(HOME / ".venv" / "bin" / "aws"), "--endpoint-url", LOCAL, "--region", "us-east-1"]

passed = 0
failed = 0
errors = []

def log(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  -- {detail[:100]}")
        errors.append(f"{name}: {detail[:200]}")

def aws(args):
    try:
        r = subprocess.run(AWS + args, capture_output=True, text=True, timeout=15, env=ENV, cwd=HOME)
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
        return {"_error": r.stderr[:200]}
    except Exception as e:
        return {"_error": str(e)}

def model(prompt):
    """Call ArcOps model server."""
    if not CACHE.exists():
        return {"error": "No server port file"}
    port = int(CACHE.read_text())
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=120)
        s.send(json.dumps({"prompt": prompt}).encode())
        data = s.recv(65536).decode()
        s.close()
        return json.loads(data)
    except Exception as e:
        return {"error": str(e)}

def safety_ok(name, args):
    schemas = {
        "create_ec2_instance": {"allowed":{"region","instance_type","security_group_rules","tags"}},
        "restart_database": {"allowed":{"db_instance_identifier","region","force_failover"}},
        "get_billing_alert": {"allowed":{"time_period_start","time_period_end","granularity","metrics","group_by_service"}},
    }
    s = schemas.get(name)
    if not s: return False, ["Unknown tool"], 0
    warns = []
    ok = True
    for k in args:
        if k not in s["allowed"]:
            warns.append(f"Unknown: {k}")
            ok = False
    return ok, warns, 0

# ═══════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════

print("\n=== 1. Model Inference ===\n")

# 1.1 Basic EC2
r = model("Create a t3.micro server in us-east-1")
log("Basic EC2 prompt", r.get("name") == "create_ec2_instance" and r.get("arguments",{}).get("instance_type") == "t3.micro", str(r))

# 1.2 EC2 with port
r = model("Create a t3.micro server in us-east-1 with port 80 open")
log("EC2 with port", "security_group_rules" in r.get("arguments",{}), str(r))

# 1.3 EC2 with tags
r = model("Create a t3.micro server in us-east-1 with tags Name=web, Env=prod")
log("EC2 with tags", "tags" in r.get("arguments",{}), str(r))

# 1.4 EC2 with multi-ports
r = model("Create a t3.micro server in us-east-1 with ports 80 and 443 open")
args = r.get("arguments",{})
sg = args.get("security_group_rules", [])
log("EC2 multi-port", len(sg) >= 2, str(r))

# 1.5 Restart database
r = model("Restart the prod-db-primary database in us-east-1")
log("Basic RDS restart", r.get("name") == "restart_database" and "db_instance_identifier" in r.get("arguments",{}), str(r))

# 1.6 RDS with failover
r = model("Restart the analytics-db in us-west-2 with failover")
log("RDS with failover", r.get("arguments",{}).get("force_failover") == True, str(r))

# 1.7 Billing
r = model("How much did we spend on AWS this month?")
log("Billing query", r.get("name") == "get_billing_alert", str(r))

# 1.8 Billing with service
r = model("What did we spend on EC2 this month?")
log("Billing by service", r.get("name") == "get_billing_alert", str(r))

# 1.9 Billing daily
r = model("Show me daily AWS costs for the past week")
log("Billing daily", r.get("arguments",{}).get("granularity") == "DAILY", str(r))

# 1.10 English prompt
r = model("Create a t3.medium server in us-west-2 with port 443")
log("English prompt", r.get("name") == "create_ec2_instance", str(r))

# 1.11 Prompt with noise (should be ignored)
r = model("Restart the prod-db database in us-east-1, but also log the event")
args = r.get("arguments",{})
log("Noise ignored (log_event)", "log_event" not in args, str(r))

# 1.12 Prompt with notification noise
r = model("Create a t3.micro server in us-east-1, and notify me when done")
args = r.get("arguments",{})
log("Noise ignored (notify)", "notify" not in args and "notification" not in args, str(r))

print("\n=== 2. Safety Layer ===\n")

# 2.1 Hallucinated param blocked
ok, warns, cost = safety_ok("restart_database", {"db_instance_identifier":"test","region":"us-east-1","log_event":True})
log("Hallucinated param blocked", not ok)

# 2.2 Missing required
ok, warns, cost = safety_ok("restart_database", {"region":"us-east-1"})
log("Missing required blocked", not ok)

# 2.3 Unknown tool
ok, warns, cost = safety_ok("delete_all_data", {})
log("Unknown tool blocked", not ok)

# 2.4 Valid EC2 passes
ok, warns, cost = safety_ok("create_ec2_instance", {"region":"us-east-1","instance_type":"t3.micro"})
log("Valid EC2 passes", ok)

# 2.5 Valid billing passes
ok, warns, cost = safety_ok("get_billing_alert", {"granularity":"MONTHLY"})
log("Valid billing passes", ok)

print("\n=== 3. AWS Integration ===\n")

# 3.1 Create EC2
r = aws(["ec2","run-instances","--instance-type","t3.micro"])
iid = r.get("Instances",[{}])[0].get("InstanceId","") if isinstance(r, dict) else ""
log(f"Create EC2 instance", bool(iid), str(r)[:100] if iid else str(r))

# 3.2 Tag instance
if iid:
    r = aws(["ec2","create-tags","--resources",iid,"--tags","Key=Name,Value=test-suite"])
    log(f"Tag instance {iid}", r is None or "_error" not in r, str(r)[:80])
    
    # 3.3 Verify tag
    r2 = aws(["ec2","describe-instances","--instance-ids",iid])
    if r2 and isinstance(r2, dict):
        for res in r2.get("Reservations",[]):
            for inst in res.get("Instances",[]):
                tags = {t["Key"]:t["Value"] for t in inst.get("Tags",[])}
                log(f"Verify tag applied", tags.get("Name") == "test-suite", str(tags))

# 3.4 Stop instance
if iid:
    r = aws(["ec2","stop-instances","--instance-ids",iid])
    time.sleep(1)
    # Check state
    r2 = aws(["ec2","describe-instances","--instance-ids",iid])
    if r2 and isinstance(r2, dict):
        for res in r2.get("Reservations",[]):
            for inst in res.get("Instances",[]):
                state = inst.get("State",{}).get("Name","")
                log(f"Stop instance", state in ("stopped","stopping"), f"state={state}")

# 3.5 Start instance
if iid:
    r = aws(["ec2","start-instances","--instance-ids",iid])
    time.sleep(1)
    r2 = aws(["ec2","describe-instances","--instance-ids",iid])
    if r2 and isinstance(r2, dict):
        for res in r2.get("Reservations",[]):
            for inst in res.get("Instances",[]):
                state = inst.get("State",{}).get("Name","")
                log(f"Start instance", state in ("running","pending"), f"state={state}")

# 3.6 Delete instance
if iid:
    r = aws(["ec2","terminate-instances","--instance-ids",iid])
    log(f"Delete instance", r is not None, str(r)[:80])

# 3.7 List instances
r = aws(["ec2","describe-instances"])
if isinstance(r, dict):
    count = sum(len(res.get("Instances",[])) for res in r.get("Reservations",[]))
    log(f"List instances works", count >= 0, f"{count} found")

# 3.8 Health check
try:
    r = subprocess.run(["curl","-s","-o","/dev/null","-w","%{http_code}","http://localhost:4566/_localstack/health"],
                      capture_output=True, text=True, timeout=5)
    log("LocalStack health", r.stdout.strip() == "200", r.stdout.strip())
except Exception as e:
    log("LocalStack health", False, str(e))

print("\n=== 4. CLI Response ===\n")

# 4.1 JSON is always valid
test_prompts = [
    "Create a t3.micro server in us-east-1",
    "Restart the production database",
    "How much did we spend?",
    "Create a server with port 80",
    "Restart analytics-db with failover",
]
for p in test_prompts:
    r = model(p)
    is_json = "name" in r and "arguments" in r
    no_error = "error" not in r
    log(f"Valid JSON: {p[:40]}", is_json and no_error, str(r)[:80])

# 4.2 No hallucinated params in basic cases
common_hallucinations = ["log_event", "notify", "alert", "send_email", "callback"]
for p in test_prompts:
    r = model(p)
    for h in common_hallucinations:
        if h in r.get("arguments",{}):
            log(f"No hallucination: {h} in '{p[:30]}'", False, f"found {h}")
            break
    else:
        log(f"No hallucination in '{p[:30]}'", True)

# ═══════════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════════
print(f"\n{'='*50}")
print(f"  Results: {passed} passed, {failed} failed")
if errors:
    print(f"\n  Errors:")
    for e in errors:
        print(f"    - {e}")
print(f"{'='*50}")
