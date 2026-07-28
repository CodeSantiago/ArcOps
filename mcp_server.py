"""MCP Server — CloudOps Agent (fine-tuned Qwen2.5-7B + LocalStack).

Exposes a tool that takes natural language and returns structured JSON
tool calls via the fine-tuned QLoRA model. Integrates with LocalStack
for end-to-end execution (no real AWS costs).

Usage:
    uv run python scripts/mcp_server.py           # start server
    uv run python scripts/mcp_server.py --test     # run self-test

Configure in opencode.json:
    "mcp": {
        "cloudops-agent": {
            "command": ["uv", "run", "python", "scripts/mcp_server.py"],
            "type": "local"
        }
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Add project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.safety import check as safety_check

# Add project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("cloudops-mcp")

# Model paths
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"
ADAPTER_PATH = str(PROJECT_ROOT / "checkpoints" / "final")

# Singleton model (loaded once)
_model = None
_tokenizer = None


def load_model():
    """Load the fine-tuned model (lazy singleton)."""
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    log.info("Loading 4-bit base model...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model = PeftModel.from_pretrained(model, ADAPTER_PATH, offload_folder="offload")
    model.eval()

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    tokenizer.pad_token = tokenizer.eos_token

    _model, _tokenizer = model, tokenizer
    log.info("Model loaded successfully")
    return model, tokenizer


def generate_tool_call(prompt: str) -> dict:
    """Convert natural language to a tool-call JSON dict."""
    model, tokenizer = load_model()

    messages = [
        {"role": "system", "content": "You are a CloudOps infrastructure assistant. Output ONLY the JSON tool call. No explanations, no markdown."},
        {"role": "user", "content": prompt},
    ]

    inputs = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
    ).to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            inputs.input_ids,
            max_new_tokens=256,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )

    reply = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
    ).strip()

    # Parse JSON from reply
    try:
        return json.loads(reply)
    except json.JSONDecodeError:
        return {"error": "model returned invalid JSON", "raw": reply}


def execute_on_localstack(tool_call: dict) -> dict:
    """Execute the tool call against LocalStack (if running)."""
    name = tool_call.get("name", "")
    args = tool_call.get("arguments", {})

    # Map tool names to AWS CLI commands
    aws_commands = {
        "create_ec2_instance": [
            "aws", "ec2", "run-instances",
            "--region", args.get("region", "us-east-1"),
            "--instance-type", args.get("instance_type", "t3.micro"),
            "--endpoint-url", "http://localhost:4566",
            "--no-cli-pager",
        ],
        "restart_database": [
            "aws", "rds", "reboot-db-instance",
            "--region", args.get("region", "us-east-1"),
            "--db-instance-identifier", args.get("db_instance_identifier", "test-db"),
            "--endpoint-url", "http://localhost:4566",
            "--no-cli-pager",
        ],
        "get_billing_alert": None,  # LocalStack doesn't support Cost Explorer
    }

    cmd = aws_commands.get(name)
    if cmd is None:
        return {"status": "skipped", "reason": f"No LocalStack mapping for {name}"}

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return {"status": "ok", "aws_output": json.loads(result.stdout)}
        else:
            return {"status": "error", "aws_error": result.stderr}
    except FileNotFoundError:
        return {"status": "error", "reason": "AWS CLI not installed"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "timed out"}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ===========================================================================
# MCP Server (stdin/stdout JSON-RPC)
# ===========================================================================

def handle_request(request: dict) -> dict:
    """Handle a single JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "0.1.0",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "arcops-mcp", "version": "0.1.0"},
        }}

    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
            {
                "name": "cloudops_plan",
                "description": "Convert a natural language instruction into a structured JSON tool call for AWS. Does NOT execute, only plans.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Natural language instruction (e.g. 'create a t3.micro EC2 server in us-east-1')"
                        }
                    },
                    "required": ["prompt"]
                }
            },
            {
                "name": "cloudops_execute",
                "description": "Convert an instruction to a JSON tool call AND execute it against LocalStack (local AWS simulator). Requires LocalStack on localhost:4566.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Natural language instruction"
                        },
                        "execute": {
                            "type": "boolean",
                            "description": "Set to true to execute against LocalStack, false to only return JSON",
                            "default": False
                        }
                    },
                    "required": ["prompt"]
                }
            }
        ]}}

    elif method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        arguments = request.get("params", {}).get("arguments", {})
        prompt = arguments.get("prompt", "")

        if not prompt:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": "Missing 'prompt' argument"}}

        try:
            tool_call = generate_tool_call(prompt)
            tc_name = tool_call.get("name", "")
            tc_args = tool_call.get("arguments", {})
            safety = safety_check(tc_name, tc_args)

            if tool_name == "cloudops_execute" and arguments.get("execute", False):
                if safety.blocked:
                    result = {"tool_call": tool_call, "safety": safety.to_dict(), "error": "Blocked by safety policy"}
                else:
                    execution = execute_on_localstack(tool_call)
                    result = {"tool_call": tool_call, "safety": safety.to_dict(), "execution": execution}
            else:
                result = {"tool_call": tool_call, "safety": safety.to_dict()}

            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [
                {"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}
            ]}}

        except Exception as e:
            log.error("Error processing request: %s", e)
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}

    elif method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    else:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main():
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
        # Quick test — no MCP, just generate and print
        logging.getLogger().setLevel(logging.WARNING)
        print(" CloudOps Agent self-test\n")
        load_model()
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

    # Run MCP server on stdin/stdout (model loads lazily on first tool call)
    log.info("CloudOps Agent MCP Server starting...")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            print(json.dumps(response), flush=True)
        except json.JSONDecodeError as e:
            log.error("Invalid JSON-RPC: %s", e)


if __name__ == "__main__":
    main()
