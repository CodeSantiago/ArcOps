#!/usr/bin/env python3
"""ArcOps TUI — Terminal dashboard for CloudOps resources."""
import json, os, subprocess, socket, time, sys
from pathlib import Path

HOME = Path.home() / "fine_tuning_model"
CACHE_FILE = Path.home() / ".arcops" / "server.port"
LOCALSTACK = "http://localhost:4566"
ENV = {**os.environ, "AWS_ACCESS_KEY_ID": "fake", "AWS_SECRET_ACCESS_KEY": "fake"}
AWS_BASE = ["uv", "run", "aws", "--endpoint-url", LOCALSTACK, "--region", "us-east-1"]

def server_port():
    if CACHE_FILE.exists():
        try:
            port = int(CACHE_FILE.read_text())
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            return port
        except: pass
    return None

def call_model(prompt):
    port = server_port()
    if not port: return None
    s = socket.create_connection(("127.0.0.1", port), timeout=60)
    s.send(json.dumps({"prompt": prompt}).encode())
    data = s.recv(65536)
    s.close()
    return json.loads(data.decode())

def aws(args):
    try:
        r = subprocess.run(AWS_BASE + args, capture_output=True, text=True, timeout=15, env=ENV, cwd=HOME)
        if r.returncode == 0:
            return json.loads(r.stdout) if r.stdout.strip() else {}
        print(f"  [aws error] {r.stderr[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [aws exception] {e}", file=sys.stderr)
        return None

def get_resources():
    items = []
    r = aws(["ec2","describe-instances"])
    if r:
        for res in r.get("Reservations", []):
            for inst in res.get("Instances", []):
                if inst.get("State",{}).get("Name","") == "terminated":
                    continue
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                tag_str = " ".join(f"{k}={v}" for k,v in tags.items()) if tags else ""
                items.append({"type":"EC2","id":inst.get("InstanceId","?"),
                    "size":inst.get("InstanceType","?"),"state":inst.get("State",{}).get("Name","?"),
                    "tags":tag_str})
    r = aws(["rds","describe-db-instances"])
    if r:
        for db in r.get("DBInstances", []):
            items.append({"type":"RDS","id":db.get("DBInstanceIdentifier","?"),
                "size":db.get("Engine","?"),"state":db.get("DBInstanceStatus","?"),"tags":""})
    return items

def action(item, cmd):
    if item["type"] == "EC2":
        aws(["ec2", cmd, "--instance-ids", item["id"]])
    elif item["type"] == "RDS":
        aws(["rds", cmd, "--db-instance-identifier", item["id"]])

def tag_instance(item, key, value=""):
    if item["type"] == "EC2":
        # Delete existing tags first (get current tags, then delete each)
        r = aws(["ec2","describe-instances","--instance-ids",item["id"]])
        if r:
            inst = r.get("Reservations",[{}])[0].get("Instances",[{}])[0]
            old_tags = [t["Key"] for t in inst.get("Tags", [])]
            if old_tags:
                delete_args = sum([["--tags", f"Key={t}"] for t in old_tags], [])
                aws(["ec2","delete-tags","--resources",item["id"]] + delete_args)
        # Add new tag
        aws(["ec2","create-tags","--resources",item["id"],"--tags",f"Key={key},Value={value}"])

def create_from_prompt(prompt):
    result = call_model(prompt)
    if not result: return "Model server not running. Start: arcops serve"
    if "error" in result: return f"Error: {result['error']}"
    tc = result if "tool_call" not in result else result["tool_call"]
    name = tc.get("name","")
    args = tc.get("arguments",{})
    if name == "create_ec2_instance":
        r = aws(["ec2","run-instances","--instance-type",args.get("instance_type","t3.micro")])
        if r:
            inst_id = r.get("Instances",[{}])[0].get("InstanceId","?")
            return f"Created {inst_id}"
    return f"JSON: {json.dumps(tc, indent=2, ensure_ascii=False)}"

def show_header():
    os.system("clear")
    print("  +------------------------------------------+")
    print("  |        > ArcOps Dashboard                 |")
    print("  +------------------------------------------+")

def list_resources(items):
    if not items:
        print("\n  No resources found.")
        return
    header = f"\n  {'#':3s} {'Type':5s} {'ID':35s} {'Size':15s} {'State':10s} {'Tags'}"
    sep = f"  {'-'*3} {'-'*5} {'-'*35} {'-'*15} {'-'*10} {'-'*30}"
    print(header)
    print(sep)
    for i, item in enumerate(items, 1):
        print(f"  {i:<3d} {item['type']:5s} {item['id']:35s} {item['size']:15s} {item['state']:10s} {item['tags']}")

def menu():
    print()
    print("  |  [c] Create (ask AI)                     |")
    print("  |  [s] Stop / [t] Start / [d] Delete       |")
    print("  |  [g] Tag resource                        |")
    print("  |  [r] Refresh     [q] Quit                |")
    print("  +------------------------------------------+")
    return input("  > ").strip()

def select_resource(items, action_name):
    if not items:
        input("  No resources. Press Enter...")
        return None
    try:
        idx = int(input(f"  Enter number to {action_name}: ")) - 1
        if 0 <= idx < len(items):
            return items[idx]
    except: pass
    return None

def main():
    while True:
        items = get_resources()
        show_header()
        list_resources(items)
        choice = menu()
        if choice == "q": break
        elif choice in ("r",""): continue
        elif choice == "c":
            prompt = input("\n  Describe resource to create: ").strip()
            if prompt:
                print("  Thinking...")
                result = create_from_prompt(prompt)
                print(f"  {result}")
                input("  Press Enter...")
        elif choice == "d":
            item = select_resource(items, "delete")
            if item: action(item, "terminate-instances" if item["type"]=="EC2" else "delete-db-instance")
            if item: input("  Press Enter...")
        elif choice == "s":
            item = select_resource(items, "stop")
            if item: action(item, "stop-instances" if item["type"]=="EC2" else "stop-db-instance")
            if item: input("  Press Enter...")
        elif choice == "t":
            item = select_resource(items, "start")
            if item: action(item, "start-instances" if item["type"]=="EC2" else "start-db-instance")
            if item: input("  Press Enter...")
        elif choice == "g":
            item = select_resource(items, "tag")
            if item:
                tag_val = input("  Tag value (e.g. my-server): ").strip()
                if tag_val:
                    tag_instance(item, "Name", tag_val)
                    print(f"  Tagged as Name={tag_val}")
                else:
                    print("  Empty tag, skipped.")
                continue

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Bye!")
