"""ArcOps exec — NL → JSON → LocalStack. End-to-end demo."""
import json, os, sys, subprocess, time

# ArcOps imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.mcp_server import generate_tool_call

LOCALSTACK_URL = os.getenv("LOCALSTACK_URL", "http://localhost:4566")

AWS_MAP = {
    "create_ec2_instance": {
        "aws_cmd": ["aws", "ec2", "run-instances"],
        "required": ["region", "instance_type"],
        "description": "EC2 instance"
    },
    "restart_database": {
        "aws_cmd": ["aws", "rds", "reboot-db-instance"],
        "required": ["db_instance_identifier", "region"],
        "description": "RDS instance"
    },
    "get_billing_alert": {
        "aws_cmd": None,
        "description": "Cost Explorer (no disponible en LocalStack)"
    }
}

def wait_for_localstack(timeout=30):
    """Esperar hasta que LocalStack esté listo."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"{LOCALSTACK_URL}/_localstack/health"],
                             capture_output=True, text=True, timeout=5)
            if r.stdout.strip() == "200":
                return True
        except:
            pass
        time.sleep(1)
    return False

def build_aws_cmd(tool_name, args):
    """Construir comando AWS CLI para el tool call (sin ejecutar)."""
    mapping = AWS_MAP.get(tool_name)
    if not mapping:
        return {"error": f"Tool {tool_name} no mapeada a AWS CLI"}

    aws_cmd = mapping["aws_cmd"].copy()
    aws_cmd.extend(["--endpoint-url", LOCALSTACK_URL])

    if tool_name == "create_ec2_instance":
        aws_cmd.extend(["--region", args.get("region", "us-east-1")])
        aws_cmd.extend(["--instance-type", args.get("instance_type", "t3.micro")])
    elif tool_name == "restart_database":
        aws_cmd.extend(["--db-instance-identifier", args.get("db_instance_identifier", "test-db")])
        aws_cmd.extend(["--region", args.get("region", "us-east-1")])
    elif tool_name == "get_billing_alert":
        return {"error": "Cost Explorer no disponible en LocalStack"}

    return {"cmd": aws_cmd}


def run_localstack(aws_cmd):
    """Ejecutar comando AWS CLI contra LocalStack."""
    try:
        result = subprocess.run(aws_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            try:
                return {"status": "ok", "aws_response": json.loads(result.stdout)}
            except:
                return {"status": "ok", "raw": result.stdout.strip()}
        else:
            return {"status": "error", "error": result.stderr.strip()}
    except FileNotFoundError:
        return {"status": "error", "error": "AWS CLI no instalado"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "timeout"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def main():
    import argparse
    parser = argparse.ArgumentParser(description="ArcOps exec — NL → AWS tool call (dry-run or live)")
    parser.add_argument("prompt", nargs="?", help="Natural language instruction")
    parser.add_argument("--live", action="store_true", help="Execute against LocalStack (requires Docker)")
    args = parser.parse_args()

    if not args.prompt:
        parser.print_help()
        return

    print(f"\n  > {args.prompt}")
    print(f"\n  ... Generating tool call...")
    tool_call = generate_tool_call(args.prompt)

    if "error" in tool_call:
        print(f"  X Error: {tool_call['error']}")
        return

    name = tool_call.get("name", "?")
    arguments = tool_call.get("arguments", {})
    print(f"  => Tool: {name}")
    print(f"     Args: {json.dumps(arguments, ensure_ascii=False)}")

    print(f"\n  ... Preparing AWS command...")
    aws_cmd = build_aws_cmd(name, arguments)

    if aws_cmd.get("error"):
        print(f"  ..  {aws_cmd['error']}")
        return

    print(f"\n  OK AWS command ready to execute:")
    print(f"\n     {' '.join(aws_cmd['cmd'])}")
    print()
    print(f"     Equivalent real AWS CLI:")
    print(f"     aws {name} --region {arguments.get('region', 'us-east-1')} \\")
    for k, v in arguments.items():
        print(f"       --{k} {v}")

    if args.live:
        print(f"\n  ... Executing against LocalStack...")
        result = run_localstack(aws_cmd["cmd"])
        if result.get("status") == "ok":
            print(f"  OK Done!")
            aws_resp = result.get("aws_response", result.get("raw", ""))
            print(f"     {json.dumps(aws_resp, ensure_ascii=False, indent=4)[:300]}")
        else:
            print(f"  X {result.get('error', 'failed')}")
            print(f"\n  Tip Make sure LocalStack is running:")
            print(f"     docker run -d --rm -p 4566:4566 localstack/localstack:3.0")
    else:
        print(f"\n  Tip To execute for real: arcops exec --live \"{args.prompt}\"")

if __name__ == "__main__":
    main()
