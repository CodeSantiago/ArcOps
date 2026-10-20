"""MCP Server — CloudOps Agent (fine-tuned Qwen2.5-7B + LocalStack).

Exposes ArcOps to MCP clients as two tools:
``cloudops_plan`` (infer only) and ``cloudops_execute`` (infer + LocalStack).

Inference and execution live in ``cloudops_fc.core``. The ML stack is
imported lazily on the first tool call, so the server boots without it and
returns a clear error if the extras are missing.

Usage:
    uv run --extra train python scripts/mcp_server.py
    uv run --extra train python scripts/mcp_server.py --test
    uv run --extra train python scripts/mcp_server.py --once "create a t3.micro"

Configure in opencode.json:
    "mcp": {
        "arcops": {
            "command": ["uv", "run", "--extra", "train", "python", "scripts/mcp_server.py"],
            "type": "local"
        }
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from cloudops_fc.core import REAL, execute_tool_call, infer  # noqa: E402
from cloudops_fc.models import resolve_model_config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("cloudops-mcp")

MCP_PROTOCOL_VERSION = "2024-11-05"


def generate_tool_call(prompt: str) -> dict[str, Any]:
    """Convert natural language to a tool-call JSON dict."""
    try:
        return infer(prompt, resolve_model_config())
    except (RuntimeError, ValueError) as exc:
        return {"error": str(exc)}


def execute_on_localstack(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool call against LocalStack (never real AWS).

    Disruptive actions require an interactive approval channel that MCP does
    not have, so they are refused rather than executed silently.
    """
    if REAL:
        return {
            "status": "blocked",
            "message": "MCP execution targets LocalStack only; unset ARC_OPS_REAL",
        }

    name = tool_call.get("name", "")
    args = tool_call.get("arguments", {})
    if not isinstance(args, dict):
        args = {}

    status, message = execute_tool_call(
        name,
        args,
        confirm_callable=None,
        env="development",
        verbose=False,
    )
    return {"status": status, "message": message}


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Handle a single JSON-RPC request (None for notifications)."""
    method = request.get("method", "")
    req_id = request.get("id")

    if method.startswith("notifications/"):
        return None

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "arcops-mcp", "version": "0.1.0"},
        }}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
            {
                "name": "cloudops_plan",
                "description": (
                    "Convert a natural language instruction into a structured "
                    "JSON tool call for AWS. Does NOT execute, only plans."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": (
                                "Natural language instruction (e.g. 'create a "
                                "t3.micro EC2 server in us-east-1')"
                            ),
                        }
                    },
                    "required": ["prompt"],
                },
            },
            {
                "name": "cloudops_execute",
                "description": (
                    "Convert an instruction to a JSON tool call AND execute it "
                    "against LocalStack (local AWS simulator). Requires "
                    "LocalStack on localhost:4566."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Natural language instruction",
                        },
                        "execute": {
                            "type": "boolean",
                            "description": (
                                "Set to true to execute against LocalStack, "
                                "false to only return JSON"
                            ),
                            "default": False,
                        },
                    },
                    "required": ["prompt"],
                },
            },
        ]}}

    if method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        arguments = request.get("params", {}).get("arguments", {})
        prompt = arguments.get("prompt", "")

        if tool_name not in ("cloudops_plan", "cloudops_execute"):
            return {"jsonrpc": "2.0", "id": req_id, "error": {
                "code": -32602, "message": f"Unknown tool: {tool_name}"
            }}
        if not prompt:
            return {"jsonrpc": "2.0", "id": req_id, "error": {
                "code": -32602, "message": "Missing 'prompt' argument"
            }}

        try:
            tool_call = generate_tool_call(prompt)
            is_error = "error" in tool_call
            if tool_name == "cloudops_execute" and arguments.get("execute", False):
                execution = execute_on_localstack(tool_call)
                is_error = is_error or execution.get("status") in (
                    "error",
                    "blocked",
                    "cancelled",
                )
                result = {"tool_call": tool_call, "execution": execution}
            else:
                result = {"tool_call": tool_call}

            payload: dict[str, Any] = {"content": [
                {"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}
            ]}
            if is_error:
                payload["isError"] = True
            return {"jsonrpc": "2.0", "id": req_id, "result": payload}
        except Exception as exc:  # pragma: no cover - defensive
            log.error("Error processing request: %s", exc)
            return {"jsonrpc": "2.0", "id": req_id, "error": {
                "code": -32000, "message": str(exc)
            }}

    return {"jsonrpc": "2.0", "id": req_id, "error": {
        "code": -32601, "message": f"Method not found: {method}"
    }}


def main() -> None:
    parser = argparse.ArgumentParser(description="CloudOps Agent MCP Server")
    parser.add_argument("--test", action="store_true", help="Run self-test")
    parser.add_argument("--once", type=str, help="Single prompt: generate and exit")
    args = parser.parse_args()

    if args.once:
        logging.getLogger().setLevel(logging.WARNING)
        result = generate_tool_call(args.once)
        print(json.dumps({"tool_call": result}, ensure_ascii=False, indent=2))
        return

    if args.test:
        logging.getLogger().setLevel(logging.WARNING)
        print(" CloudOps Agent self-test\n")
        tests = [
            "Create a t3.micro EC2 server in us-east-1 with port 80",
            "Restart the production database",
            "How much did we spend this month on AWS?",
        ]
        for test in tests:
            result = generate_tool_call(test)
            print(f"  > {test}")
            print(f"  => {json.dumps(result, ensure_ascii=False)}\n")
        return

    log.info("CloudOps Agent MCP Server starting...")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            log.error("Invalid JSON-RPC: %s", exc)
            continue
        response = handle_request(request)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
