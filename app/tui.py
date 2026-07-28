#!/usr/bin/env python3
"""ArcOps TUI — Terminal dashboard. Run: uv run python app/tui.py"""
import json, os, subprocess, socket, time, sys, itertools
from pathlib import Path

HOME = Path.home() / "fine_tuning_model"
CACHE = Path.home() / ".arcops" / "server.port"
LOCAL = "http://localhost:4566"
ENV = {**os.environ, "AWS_ACCESS_KEY_ID": "fake", "AWS_SECRET_ACCESS_KEY": "fake"}
AWS_BASE = ["uv", "run", "aws", "--endpoint-url", LOCAL, "--region", "us-east-1"]

LS_START_TIME = None  # When LocalStack was started

def aws(args):
    try:
        r = subprocess.run(AWS_BASE + args, capture_output=True, text=True, timeout=15, env=ENV, cwd=HOME)
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except: pass
    return None

def ls_uptime():
    if LS_START_TIME is None: return None
    return int(time.time() - LS_START_TIME)

def ls_check():
    for _ in range(5):  # 5 retries, 1s apart
        try:
            r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:4566/_localstack/health"],
                             capture_output=True, text=True, timeout=5)
            code = r.stdout.strip()
            if code == "200":
                return True
        except: pass
        time.sleep(1)
    return False

def get_all():
    items = []
    r = aws(["ec2","describe-instances"])
    if r:
        for res in r.get("Reservations", []):
            for inst in res.get("Instances", []):
                s = inst.get("State",{}).get("Name","")
                if s == "terminated": continue
                tags = {t["Key"]:t["Value"] for t in inst.get("Tags", [])}
                ts = " ".join(f"{k}={v}" for k,v in tags.items()) if tags else ""
                items.append({"t":"EC2","id":inst.get("InstanceId","?"),"info":f"{inst.get('InstanceType','?')} {s}","state":s,"tags":ts})
    r = aws(["rds","describe-db-instances"])
    if r:
        for db in r.get("DBInstances", []):
            items.append({"t":"RDS","id":db.get("DBInstanceIdentifier","?"),"info":f"{db.get('Engine','?')} {db.get('DBInstanceStatus','?')}","state":db.get("DBInstanceStatus","?"),"tags":""})
    return items

def act(item, cmd):
    if item["t"] == "EC2":
        aws(["ec2", cmd, "--instance-ids", item["id"]])
    else:
        aws(["rds","delete-db-instance","--db-instance-identifier",item["id"],"--skip-final-snapshot"])

def tag_it(item, key, val):
    r = aws(["ec2","describe-instances","--instance-ids",item["id"]])
    if r:
        for res in r.get("Reservations",[]):
            for inst in res.get("Instances",[]):
                for t in inst.get("Tags",[]):
                    aws(["ec2","delete-tags","--resources",item["id"],"--tags",f"Key={t['Key']}"])
    aws(["ec2","create-tags","--resources",item["id"],"--tags",f"Key={key},Value={val}"])

def safety(name, args):
    warns = []
    ok = True
    cost = 0
    schemas = {
        "create_ec2_instance": {"allowed":{"region","instance_type","security_group_rules","tags"},"required":["region","instance_type"],"disruptive":False},
        "restart_database": {"allowed":{"db_instance_identifier","region","force_failover"},"required":["db_instance_identifier","region"],"disruptive":True},
        "get_billing_alert": {"allowed":{"time_period_start","time_period_end","granularity","metrics","group_by_service"},"required":[],"disruptive":False},
    }
    s = schemas.get(name)
    if not s:
        return False, [f"Unknown tool: {name}"], 0
    for k in args:
        if k not in s["allowed"]:
            warns.append(f"Unknown param '{k}'")
            ok = False
    for k in s["required"]:
        if k not in args:
            warns.append(f"Missing: {k}")
            ok = False
    if s.get("disruptive"):
        warns.append("Causes downtime — approval needed")
    if name == "create_ec2_instance":
        prices = {"t3.micro":8,"t3.small":15,"t3.medium":30,"m5.large":70,"m5.xlarge":140}
        inst = args.get("instance_type","t3.micro")
        cost = prices.get(inst, 20)
        warns.append(f"~${cost}/mo ({inst})")
    return ok, warns, cost

def create(prompt):
    global LS_START_TIME
    if not ls_check():
        return "error", "LocalStack not running. Press [l] to launch."
    
    port = None
    if CACHE.exists():
        try:
            port = int(CACHE.read_text())
            s = socket.create_connection(("127.0.0.1", port), timeout=3)
            s.close()
        except: port = None
    if not port:
        return "error", "Model server not running. In WSL: arcops serve"
    
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=120)
        s.send(json.dumps({"prompt":prompt}).encode())
        raw = s.recv(65536).decode()
        s.close()
        result = json.loads(raw)
        name = result.get("name","")
        args = result.get("arguments",{})
        
        ok, warns, cost = safety(name, args)
        print(f"\n  -- Safety Check --")
        for w in warns:
            print(f"  {w}")
        print()
        
        if not ok:
            return "blocked", "Blocked by safety policy"
        
        # Ask approval for disruptive actions
        if any("downtime" in w for w in warns):
            confirm = input("  Approve this action? (y/n): ").strip().lower()
            if confirm != "y":
                return "cancelled", "Cancelled"
        
        if name == "create_ec2_instance":
            r = aws(["ec2","run-instances","--instance-type",args.get("instance_type","t3.micro")])
            if r and isinstance(r, dict) and "Instances" in r:
                iid = r.get("Instances",[{}])[0].get("InstanceId","?")
                cost_msg = f" (~${cost}/mo)" if cost else ""
                return "ok", f"Created {iid}{cost_msg}"
            return "error", "AWS command failed — LocalStack may be down"
        elif name == "restart_database":
            r = aws(["rds","reboot-db-instance","--db-instance-identifier",args.get("db_instance_identifier","test-db")])
            if r is not None:
                return "ok", "Database rebooting"
            return "error", "AWS command failed — LocalStack may be down"
        elif name == "get_billing_alert":
            return "ok", "Billing (read-only)"
        return "ok", f"JSON: {json.dumps(result)}"
    except Exception as e:
        return "error", f"Error: {e}"

def main():
    global LS_START_TIME
    os.system("clear")
    last_known_up = None  # cache for display even if health flickers
    
    while True:
        ls_on = ls_check()
        items = get_all() if ls_on else []
        
        # Cache the last known uptime for display
        if ls_on:
            last_known_up = int(time.time() - LS_START_TIME) if LS_START_TIME else 0
        elif last_known_up is not None:
            last_known_up += 1  # increment while waiting
        
        # ── Header ──
        print("  +------------------------------------------+")
        print("  |        ArcOps Dashboard                   |")
        if ls_on:
            up = int(time.time() - LS_START_TIME) if LS_START_TIME else 0
            print(f"  |  LocalStack: RUNNING  ({up}s uptime)      |")
        elif last_known_up is not None and last_known_up < 5:
            print(f"  |  LocalStack: RECENTLY STOPPED             |")
        else:
            print(f"  |  LocalStack: STOPPED                       |")
            print(f"  |  Press [l] to launch                       |")
        print("  +------------------------------------------+")
        
        # ── Resources ──
        if ls_on and items:
            print(f"  {'#':3s} {'Type':5s} {'ID':32s} {'Info':22s} {'Tags'}")
            print(f"  {'-'*3} {'-'*5} {'-'*32} {'-'*22} {'-'*25}")
            for i, item in enumerate(items, 1):
                print(f"  {i:<3d} {item['t']:5s} {item['id']:32s} {item['info']:22s} {item['tags']}")
        elif ls_on:
            print("\n  No resources. Press [c] to create one.\n")
        else:
            print()
        
        # ── Menu ──
        print("  +------------------------------------------+")
        opts = "  |  [c] Create  [s] Stop  [t] Start  [d] Delete  |\n"
        opts += "  |  [g] Tag     [r] Refresh"
        if not ls_on: opts += "  [l] Launch"
        opts += "  [q] Quit  |"
        print(opts)
        print("  +------------------------------------------+")
        
        ch = input("  > ").strip().lower()
        os.system("clear")
        
        if ch == "q": break
        elif ch == "r": continue
        elif ch == "l":
            if ls_on:
                # Show diagnostics
                r = subprocess.run(["docker","ps","--filter","name=localstack","--format","{{.Status}}"], capture_output=True, text=True, timeout=10)
                status = r.stdout.strip() or "not found"
                print(f"  LocalStack container: {status}")
                h = subprocess.run(["curl","-s","-o","/dev/null","-w","%{http_code}","http://localhost:4566/_localstack/health"], capture_output=True, text=True, timeout=5)
                print(f"  Health endpoint: {h.stdout.strip()}")
                input("  Press Enter...")
                os.system("clear")
                continue
            print("  Starting LocalStack...")
            r = subprocess.run(["docker","start","localstack"], capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                r = subprocess.run(["docker","run","-d","--name","localstack","-p","4566:4566",
                                   "-e","LOCALSTACK_AUTH_TOKEN=ls-DIBaXisO-gUza-9468-YeQA-wUCo19799a1f",
                                   "localstack/localstack"],
                                  capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                spin = itertools.cycle(["[•]","[•>]","[•>•]","[>•>]"])
                for _ in range(40):
                    sys.stdout.write(f"\r  Booting LocalStack... {next(spin)} ")
                    sys.stdout.flush()
                    time.sleep(1)
                    if ls_check():
                        LS_START_TIME = time.time()
                        break
                print(f"\r  LocalStack started!                     ")
            else:
                print(f"\r  Failed: {r.stderr.strip()[:200]}")
            input("  Press Enter...")
            os.system("clear")
            continue
        
        elif ch == "c":
            if not ls_on:
                print("  LocalStack is not running. Press [l] to launch.")
                input("  Press Enter...")
                os.system("clear")
                continue
            p = input("  Prompt: ").strip()
            if p:
                status, msg = create(p)
                print(f"  [{status}] {msg}")
                if status == "ok" and msg.startswith("Created"):
                    print("  Resource created! Press Enter to refresh.")
                input("  Press Enter...")
            os.system("clear")
            continue
        
        elif not items:
            print("  No resources to manage.")
            input("  Press Enter...")
            os.system("clear")
            continue
        
        try:
            if ch == "d":
                i = int(input("  Number to delete: ")) - 1
                if 0 <= i < len(items):
                    act(items[i], "terminate-instances" if items[i]["t"]=="EC2" else "")
                    print(f"  Deleted {items[i]['id']}")
            elif ch == "s":
                i = int(input("  Number to stop: ")) - 1
                if 0 <= i < len(items):
                    act(items[i], "stop-instances")
                    print(f"  Stopped {items[i]['id']}")
            elif ch == "t":
                i = int(input("  Number to start: ")) - 1
                if 0 <= i < len(items):
                    act(items[i], "start-instances")
                    print(f"  Started {items[i]['id']}")
            elif ch == "g":
                i = int(input("  Number to tag: ")) - 1
                if 0 <= i < len(items):
                    v = input("  Tag value: ").strip()
                    if v:
                        tag_it(items[i], "Name", v)
                        print(f"  Tagged as Name={v}")
        except: pass
        
        input("  Press Enter...")
        os.system("clear")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n  Bye!")
