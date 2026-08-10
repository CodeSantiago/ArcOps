"""ArcOps exec — NL → JSON → LocalStack. End-to-end demo.

Default target is LocalStack (safe sandbox). Real AWS requires BOTH the
``--real`` flag AND ``ARC_OPS_REAL=1`` in the environment, plus an explicit
interactive confirmation — never run against real AWS by accident.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT_ROOT / "src"
for _p in (str(_PROJECT_ROOT), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from cloudops_fc.safety import check  # noqa: E402
from scripts.mcp_server import generate_tool_call  # noqa: E402

LOCALSTACK_URL = os.getenv("LOCALSTACK_URL", "http://localhost:4566")

AWS_MAP: dict[str, dict] = {
    "create_ec2_instance": {
        "aws_cmd": ["aws", "ec2", "run-instances"],
        "required": ["region", "instance_type"],
        "description": "EC2 instance",
    },
    "restart_database": {
        "aws_cmd": ["aws", "rds", "reboot-db-instance"],
        "required": ["db_instance_identifier", "region"],
        "description": "RDS instance",
    },
    "get_billing_alert": {
        "aws_cmd": None,
        "description": "Cost Explorer (not supported by LocalStack)",
    },
}


def wait_for_localstack(timeout: int = 30) -> bool:
    """Wait until LocalStack is ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 f"{LOCALSTACK_URL}/_localstack/health"],
                capture_output=True, text=True, timeout=5,
            )
            if r.stdout.strip() == "200":
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def build_aws_cmd(tool_name: str, args: dict, real: bool = False) -> dict:
    """Build the AWS CLI command for the tool call (without executing).

    Required fields come from the canonical safety schema — missing required
    identifiers return an error instead of silently defaulting (no test-db).
    """
    mapping = AWS_MAP.get(tool_name)
    if not mapping:
        return {"error": f"Tool {tool_name} has no AWS CLI mapping"}

    result = check(tool_name, args, env="development")
    if result.blocked or result.errors:
        return {"error": "; ".join(result.errors) or f"Safety check failed for {tool_name}"}

    aws_cmd = mapping["aws_cmd"].copy()
    if not real:
        aws_cmd.extend(["--endpoint-url", LOCALSTACK_URL])
    aws_cmd.append("--no-cli-pager")

    if tool_name == "create_ec2_instance":
        aws_cmd.extend(["--region", args["region"]])
        aws_cmd.extend(["--instance-type", args["instance_type"]])
    elif tool_name == "restart_database":
        aws_cmd.extend(["--db-instance-identifier", args["db_instance_identifier"]])
        aws_cmd.extend(["--region", args["region"]])
    elif tool_name == "get_billing_alert":
        return {"error": "Cost Explorer is not supported by LocalStack"}

    return {"cmd": aws_cmd}


def run_localstack(aws_cmd: list[str]) -> dict:
    """Run the AWS CLI command against LocalStack."""
    try:
        result = subprocess.run(aws_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            try:
                return {"status": "ok", "aws_response": json.loads(result.stdout)}
            except json.JSONDecodeError:
                return {"status": "ok", "raw": result.stdout.strip()}
        return {"status": "error", "error": result.stderr.strip()}
    except FileNotFoundError:
        return {"status": "error", "error": "AWS CLI is not installed"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "timeout"}
    except Exception as exc:  # pragma: no cover - defensive
        return {"status": "error", "error": str(exc)}


def _confirm_real_aws() -> bool:
    """Require an explicit interactive confirmation for real-AWS actions."""
    answer = input(
        "  WARNING: this targets REAL AWS and may incur real costs.\n"
        "  Type 'yes' to confirm: "
    ).strip().lower()
    return answer == "yes"


def main(argv: list[str] | None = None) -> int:
    """Run the exec demo. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        description="ArcOps exec — NL → AWS tool call (LocalStack by default)"
    )
    parser.add_argument("prompt", nargs="?", help="Natural language instruction")
    parser.add_argument(
        "--live", action="store_true",
        help="Execute against LocalStack (requires Docker)",
    )
    parser.add_argument(
        "--real", action="store_true",
        help=(
            "Target REAL AWS. Requires ARC_OPS_REAL=1 in the environment "
            "and an interactive confirmation."
        ),
    )
    args = parser.parse_args(argv)

    if not args.prompt:
        parser.print_help()
        return 0

    real = args.real
    if real and os.environ.get("ARC_OPS_REAL", "") != "1":
        print(
            "  ERROR: --real requires the explicit environment flag "
            "ARC_OPS_REAL=1 (protects against accidental real-AWS use)."
        )
        return 2

    print(f"\n  > {args.prompt}")
    print("\n  ... Generating tool call...")
    tool_call = generate_tool_call(args.prompt)

    if "error" in tool_call:
        print(f"  X Error: {tool_call['error']}")
        return 1

    name = tool_call.get("name", "?")
    arguments = tool_call.get("arguments", {})
    print(f"  => Tool: {name}")
    print(f"     Args: {json.dumps(arguments, ensure_ascii=False)}")

    print("\n  ... Preparing AWS command...")
    aws_cmd = build_aws_cmd(name, arguments, real=real)

    if aws_cmd.get("error"):
        print(f"  ..  {aws_cmd['error']}")
        return 1

    target = "REAL AWS" if real else "LocalStack"
    print(f"\n  OK AWS command ready to execute against {target}:")
    print(f"\n     {' '.join(aws_cmd['cmd'])}")

    if real and not _confirm_real_aws():
        print("\n  Cancelled — no action executed.")
        return 0

    if args.live or real:
        print(f"\n  ... Executing against {target}...")
        result = run_localstack(aws_cmd["cmd"]) if not real else _run(aws_cmd["cmd"])
        if result.get("status") == "ok":
            print("  OK Done!")
            aws_resp = result.get("aws_response", result.get("raw", ""))
            print(f"     {json.dumps(aws_resp, ensure_ascii=False, indent=4)[:300]}")
        else:
            print(f"  X {result.get('error', 'failed')}")
            if not real:
                print("\n  Tip Make sure LocalStack is running:")
                print("     docker run -d --rm -p 4566:4566 localstack/localstack:3.0")
    else:
        mode = "--real" if real else "--live"
        print(f"\n  Tip To execute for real: arcops exec {mode} \"{args.prompt}\"")
    return 0


def _run(aws_cmd: list[str]) -> dict:
    """Run an AWS CLI command without the LocalStack endpoint (real AWS)."""
    return run_localstack(aws_cmd)


if __name__ == "__main__":
    sys.exit(main())
