#!/usr/bin/env python3
"""
ArcOps TUI — Terminal dashboard for CloudOps resources.
Usage: uv run python app/tui.py
"""
import json, os, subprocess, socket, time, sys
from pathlib import Path

CACHE_FILE = Path.home() / ".arcops" / "server.port"
LOCALSTACK = "http://localhost:4566"
ENV = {**os.environ, "AWS_ACCESS_KEY_ID": "fake", "AWS_SECRET_ACCESS_KEY": "fake"}

# ── API ───────────────────────────────────────────────────────────────────

def server_port():
    if CACHE_FILE.exists():
        try:
            port = int(CACHE_FILE.read_text())
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            return port
        except:
            pass
    return None

def call_model(prompt):
    port = server_port()
    if not port:
        return None
    s = socket.create_connection(("127.0.0.1", port), timeout=60)
    s.send(json.dumps({"prompt": prompt}).encode())
    data = s.recv(65536)
    s.close()
    return json.loads(data.decode())

def aws(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=ENV)
        if r.returncode == 0:
            return json.loads(r.stdout) if r.stdout else {}
        return None
    except: return None

def get_resources():
    items = []
    r = aws(["aws", "ec2", "describe-instances", "--endpoint-url", LOCALSTACK])
    if r:
        for res in r.get("Reservations", []):
            for inst in res.get("Instances", []):
                items.append({"type": "🖥", "id": inst.get("InstanceId","?"),
                    "info": f"{inst.get('InstanceType','?')}  {inst.get('State',{}).get('Name','?')}",
                    "region": inst.get("Placement",{}).get("AvailabilityZone","?")[:9]})
    r = aws(["aws", "rds", "describe-db-instances", "--endpoint-url", LOCALSTACK])
    if r:
        for db in r.get("DBInstances", []):
            items.append({"type": "🗄", "id": db.get("DBInstanceIdentifier","?"),
                "info": f"{db.get('Engine','?')}  {db.get('DBInstanceStatus','?')}",
                "region": db.get("AvailabilityZone","?")[:9]})
    return items

def delete_resource(item):
    if item["type"] == "🖥":
        aws(["aws","ec2","terminate-instances","--endpoint-url",LOCALSTACK,"--instance-ids",item["id"]])
    else:
        aws(["aws","rds","delete-db-instance","--endpoint-url",LOCALSTACK,"--db-instance-identifier",item["id"],"--skip-final-snapshot"])

def create_from_prompt(prompt):
    result = call_model(prompt)
    if not result: return "⚠️  Server not running. Run: arcops serve"
    if "error" in result: return f"❌ {result['error']}"
    tc = result if "tool_call" not in result else result["tool_call"]
    name = tc.get("name","")
    args = tc.get("arguments",{})
    if name == "create_ec2_instance":
        r = aws(["aws","ec2","run-instances","--endpoint-url",LOCALSTACK,
                 "--region",args.get("region","us-east-1"),"--instance-type",args.get("instance_type","t3.micro")])
        if r: return f"✅ Created {r.get('Instances',[{}])[0].get('InstanceId','?')}"
    elif name == "restart_database":
        r = aws(["aws","rds","reboot-db-instance","--endpoint-url",LOCALSTACK,
                 "--db-instance-identifier",args.get("db_instance_identifier","test-db"),"--region",args.get("region","us-east-1")])
        if r: return "✅ Database rebooting"
    return f"⏭️  {name} (not available in LocalStack)"

# ── UI ────────────────────────────────────────────────────────────────────

def clear(): os.system("clear")

def show():
    clear()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║        ⚡ ArcOps Dashboard               ║")
    print("  ╚══════════════════════════════════════════╝")
    print()

def menu():
    print()
    print("  ┌──────────────────────────────────────────┐")
    print("  │  [1] List resources                      │")
    print("  │  [2] Create resource (ask AI)            │")
    print("  │  [3] Delete resource                     │")
    print("  │  [4] Refresh                             │")
    print("  │  [q] Quit                                │")
    print("  └──────────────────────────────────────────┘")
    return input("  > ").strip()

def list_resources(items):
    if not items:
        print("\n  ⚡ No resources found.")
        return
    print(f"\n  {'Type':5s} {'ID':30s} {'Info':25s}")
    print(f"  {'─'*5} {'─'*30} {'─'*25}")
    for i, item in enumerate(items, 1):
        print(f"  {i:<3d} {item['type']} {item['id']:30s} {item['info']:25s}")

def main():
    while True:
        items = get_resources()
        show()
        list_resources(items)
        choice = menu()
        if choice == "q": break
        elif choice in ("1","4"): continue
        elif choice == "2":
            print("\n  📝 Describe what to create (e.g. 'Create a t3.micro server'):")
            prompt = input("  > ").strip()
            if prompt:
                print("\n  ⏳ Thinking...")
                result = create_from_prompt(prompt)
                print(f"  {result}")
                input("\n  Press Enter to continue...")
        elif choice == "3":
            if not items:
                input("  Nothing to delete. Press Enter...")
                continue
            print("\n  Enter number to delete (0 to cancel):")
            try:
                idx = int(input("  > ")) - 1
                if 0 <= idx < len(items):
                    delete_resource(items[idx])
                    print(f"  🗑  Deleted {items[idx]['id']}")
                    input("  Press Enter...")
            except: pass

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Bye!")
