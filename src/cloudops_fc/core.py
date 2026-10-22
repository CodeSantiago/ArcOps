"""ArcOps shared engine — the single core behind every interface.

This module is the one place where inference and AWS execution live:

- ``infer()`` + ``_load_runtime()`` convert natural language into a JSON
  tool call. The ML stack (torch/transformers/peft) is imported lazily so
  the module itself imports without the ML extras installed.
- The AWS layer (``aws``, ``ls_check``, ``get_all``, ``act``, ``tag_it``,
  ``create``) executes tool calls against LocalStack by default, or real
  AWS when ``ARC_OPS_REAL=1``. Destructive actions require an explicit
  confirmation (a ``confirm_callable``); when none is provided they are
  refused.

Both the CLI face (``cloudops_fc.cli``), the TUI (``cloudops_fc.tui``),
the API, the MCP server, and ``app/exec.py`` import from here — there is no
duplicated inference or AWS logic.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, cast
from urllib.error import URLError
from urllib.request import urlopen

from cloudops_fc.models import ModelConfig, resolve_model_config
from cloudops_fc.safety import SafetyResult, check

SYSTEM_PROMPT = (
    "You are a CloudOps infrastructure assistant. "
    "Output ONLY the JSON tool call. No explanations, no markdown."
)

MAX_NEW_TOKENS = 256


# ── AWS execution layer (LocalStack by default, real AWS opt-in) ────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]

REAL = os.environ.get("ARC_OPS_REAL", "") == "1"
LOCAL = os.environ.get("LOCALSTACK_URL", "http://localhost:4566")
# LocalStack accepts any access key/secret pair; keep them injectable for CI
ENV = {
    **os.environ,
    "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", "test"),
    "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
}
AWS_EXE = shutil.which("aws") or "aws"
AWS_BASE = [AWS_EXE, "--region", os.environ.get("AWS_REGION", "us-east-1")]

if not REAL:
    AWS_BASE += ["--endpoint-url", LOCAL]


def aws(args: list[str]) -> Any:
    """Run an AWS CLI call and return parsed JSON, or None on failure."""
    try:
        r = subprocess.run(
            AWS_BASE + args,
            capture_output=True,
            text=True,
            timeout=30,
            env=ENV,
            cwd=PROJECT_ROOT,
        )
        if r.returncode == 0:
            if r.stdout.strip():
                return json.loads(r.stdout)
            return {}
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        pass
    return None


def ls_check() -> bool:
    """Return True when LocalStack's health endpoint answers 200."""
    for _ in range(5):  # 5 retries, 1s apart
        try:
            with urlopen(f"{LOCAL}/_localstack/health", timeout=5) as response:
                if response.status == 200:
                    return True
        except (OSError, URLError, ValueError):
            pass
        time.sleep(1)
    return False


def get_all() -> list[dict[str, Any]]:
    """List EC2 instances and RDS databases as dashboard rows."""
    items: list[dict[str, Any]] = []
    r = aws(["ec2", "describe-instances"])
    if r:
        for res in r.get("Reservations", []):
            for inst in res.get("Instances", []):
                state = inst.get("State", {}).get("Name", "")
                if state == "terminated":
                    continue
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                tag_str = " ".join(f"{k}={v}" for k, v in tags.items()) if tags else ""
                items.append({
                    "t": "EC2",
                    "id": inst.get("InstanceId", "?"),
                    "info": f"{inst.get('InstanceType', '?')} {state}",
                    "state": state,
                    "tags": tag_str,
                })
    r = aws(["rds", "describe-db-instances"])
    if r:
        for db in r.get("DBInstances", []):
            items.append({
                "t": "RDS",
                "id": db.get("DBInstanceIdentifier", "?"),
                "info": f"{db.get('Engine', '?')} {db.get('DBInstanceStatus', '?')}",
                "state": db.get("DBInstanceStatus", "?"),
                "tags": "",
            })
    return items


def act(
    item: dict[str, Any],
    cmd: str,
    confirm_callable: Callable[[str], bool] | None = None,
) -> tuple[str, str]:
    """Run a resource action and return ``(status, message)``.

    Destructive actions (EC2 terminate, RDS delete) require confirmation.
    When a destructive action needs confirmation and no callable was
    provided, the action is refused.
    """
    target = "REAL AWS" if REAL else "LocalStack"
    resource_type = item.get("t")
    resource_id = str(item.get("id", "?"))

    if resource_type == "RDS":
        if cmd != "delete-db-instance":
            return "error", f"RDS does not support '{cmd}'; use delete-db-instance"
        label = f"DELETE {resource_id}"
        needs_confirmation = True
        verb = "Deleted"
    elif resource_type == "EC2":
        verbs = {
            "terminate-instances": "Terminated",
            "stop-instances": "Stopped",
            "start-instances": "Started",
        }
        labels = {
            "terminate-instances": "TERMINATE",
            "stop-instances": "STOP",
            "start-instances": "START",
        }
        if cmd not in verbs:
            return "error", f"Unsupported EC2 action '{cmd}'"
        label = f"{labels[cmd]} {resource_id}"
        needs_confirmation = cmd == "terminate-instances"
        verb = verbs[cmd]
    else:
        return "error", f"Unknown resource type: {resource_type}"

    if needs_confirmation:
        if confirm_callable is None:
            return "cancelled", f"Confirmation required for {label} on {target}"
        if not confirm_callable(f"{label} on {target}?"):
            return "cancelled", f"Cancelled: {resource_id}"

    if resource_type == "EC2":
        result = aws(["ec2", cmd, "--instance-ids", resource_id])
    else:
        result = aws([
            "rds",
            "delete-db-instance",
            "--db-instance-identifier",
            resource_id,
            "--skip-final-snapshot",
        ])

    if result is None:
        return "error", f"AWS call failed for {label} on {target}"
    return "ok", f"{verb} {resource_id}"


def tag_it(item: dict[str, Any], key: str, val: str) -> tuple[str, str]:
    """Upsert a tag on an EC2 instance without touching its other tags."""
    if item.get("t") != "EC2":
        return "error", "Tagging is only supported for EC2 resources"
    resource_id = str(item.get("id", "?"))
    result = aws([
        "ec2",
        "create-tags",
        "--resources",
        resource_id,
        "--tags",
        f"Key={key},Value={val}",
    ])
    if result is None:
        return "error", f"Could not tag {resource_id}"
    return "ok", f"Tagged {resource_id} as {key}={val}"


def _print_safety(safety: SafetyResult) -> None:
    if not (safety.warnings or safety.errors):
        return
    print("\n  -- Safety Check --")
    for warning in safety.warnings:
        print(f"  {warning}")
    for error in safety.errors:
        print(f"  {error}")
    print()


def _approval(
    safety: SafetyResult,
    confirm_callable: Callable[[str], bool] | None,
) -> tuple[bool, str]:
    if not (safety.requires_approval or REAL):
        return True, ""
    if confirm_callable is None:
        return False, "Confirmation required but no confirm callback provided"
    target = "REAL AWS" if REAL else "LocalStack"
    if not confirm_callable(f"Approve this action on {target}?"):
        return False, "Cancelled"
    return True, ""


def create(
    prompt: str,
    confirm_callable: Callable[[str], bool] | None = None,
) -> tuple[str, str]:
    """Generate a tool call from a prompt, safety-check it, and execute.

    Runs inference in-process (the model loads once, ~30s on first call),
    then validates the result with the canonical safety layer. Returns a
    ``(status, message)`` pair where status is one of ``ok``, ``blocked``,
    ``cancelled``, or ``error``.
    """
    if not REAL and not ls_check():
        return "error", "LocalStack not running. Press [l] to launch."

    try:
        result = infer(prompt, resolve_model_config())
    except RuntimeError as exc:
        return "error", str(exc)

    name = result.get("name", "")
    args = result.get("arguments", {})
    if not name or not isinstance(args, dict):
        return "error", "Model returned no tool call"

    safety = check(name, args, env="development")
    _print_safety(safety)
    if safety.blocked or not safety.passed:
        return "blocked", "Blocked by safety policy"

    approved, message = _approval(safety, confirm_callable)
    if not approved:
        return "cancelled", message

    status, message = _execute_tool_call(name, args)
    if status == "ok" and safety.estimated_cost:
        message += f" (~${safety.estimated_cost:.0f}/mo)"
    return status, message


def execute_tool_call(
    name: str,
    args: dict[str, Any],
    confirm_callable: Callable[[str], bool] | None = None,
    env: str = "development",
    verbose: bool = True,
) -> tuple[str, str]:
    """Safety-check and execute an already generated tool call."""
    safety = check(name, args, env=env)
    if verbose:
        _print_safety(safety)
    if safety.blocked or not safety.passed:
        return "blocked", "Blocked by safety policy"

    approved, message = _approval(safety, confirm_callable)
    if not approved:
        return "cancelled", message
    return _execute_tool_call(name, args)


def _execute_tool_call(name: str, args: dict[str, Any]) -> tuple[str, str]:
    if name == "create_ec2_instance":
        rules = args.get("security_group_rules") or []
        group_id: str | None = None
        if rules:
            group_id = _create_security_group(args, rules)
            if group_id is None:
                return (
                    "error",
                    "Could not create the requested security group; refusing "
                    "to launch without the requested rules",
                )
        try:
            command = build_run_instances_cmd(args, group_id)
        except (KeyError, TypeError, ValueError) as exc:
            return "error", f"Invalid create_ec2_instance arguments: {exc}"

        result = aws(command)
        if isinstance(result, dict) and result.get("Instances"):
            instance_id = result["Instances"][0].get("InstanceId", "?")
            return "ok", f"Created {instance_id}"
        if group_id:
            aws([
                "ec2",
                "delete-security-group",
                "--region",
                str(args["region"]),
                "--group-id",
                group_id,
            ])
        return "error", "AWS command failed — LocalStack may be down"

    if name == "restart_database":
        try:
            command = build_reboot_db_cmd(args)
        except (KeyError, TypeError, ValueError) as exc:
            return "error", f"Invalid restart_database arguments: {exc}"
        result = aws(command)
        if result is not None:
            return "ok", "Database rebooting"
        return "error", "AWS command failed — LocalStack may be down"

    if name == "get_billing_alert":
        return _run_billing(args)

    return "error", f"Unknown tool: {name}"


def build_run_instances_cmd(
    args: dict[str, Any],
    security_group_id: str | None = None,
) -> list[str]:
    """Build the ``aws ec2 run-instances`` command from tool arguments."""
    command = [
        "ec2",
        "run-instances",
        "--region",
        str(args["region"]),
        "--instance-type",
        str(args["instance_type"]),
    ]

    if args.get("ami_id"):
        command += ["--image-id", str(args["ami_id"])]
    elif not REAL:
        command += [
            "--image-id",
            os.environ.get("ARC_OPS_DEFAULT_AMI", "ami-12345678"),
        ]
    else:
        raise ValueError("ami_id is required for real AWS")
    if args.get("key_name"):
        command += ["--key-name", str(args["key_name"])]
    if args.get("subnet_id"):
        command += ["--subnet-id", str(args["subnet_id"])]

    count = max(1, int(args.get("min_count") or 1))
    command += ["--count", str(count)]

    if args.get("associate_public_ip") is True:
        command.append("--associate-public-ip-address")
    elif args.get("associate_public_ip") is False:
        command.append("--no-associate-public-ip-address")

    if security_group_id:
        command += ["--security-group-ids", security_group_id]

    tags = args.get("tags") or []
    if isinstance(tags, list):
        tag_list = [
            {"Key": str(tag["key"]), "Value": str(tag["value"])}
            for tag in tags
            if isinstance(tag, dict) and "key" in tag and "value" in tag
        ]
        if tag_list:
            specification = [{"ResourceType": "instance", "Tags": tag_list}]
            command += [
                "--tag-specifications",
                json.dumps(specification, separators=(",", ":")),
            ]

    return command


def build_reboot_db_cmd(args: dict[str, Any]) -> list[str]:
    """Build the ``aws rds reboot-db-instance`` command from tool arguments."""
    command = [
        "rds",
        "reboot-db-instance",
        "--db-instance-identifier",
        str(args["db_instance_identifier"]),
        "--region",
        str(args["region"]),
    ]
    if args.get("force_failover") is True:
        command.append("--force-failover")
    return command


def _create_security_group(args: dict[str, Any], rules: list[Any]) -> str | None:
    region = str(args["region"])
    name = f"arcops-sg-{uuid.uuid4().hex[:8]}"
    created = aws([
        "ec2",
        "create-security-group",
        "--region",
        region,
        "--group-name",
        name,
        "--description",
        "ArcOps managed security group",
    ])
    if not isinstance(created, dict) or not created.get("GroupId"):
        return None

    group_id = str(created["GroupId"])
    for rule in rules:
        if not isinstance(rule, dict):
            return None
        protocol = str(rule.get("protocol", "tcp"))
        port = rule.get("port")
        cidr = str(rule.get("cidr", "0.0.0.0/0"))
        if port is None:
            if protocol != "icmp":
                return None
            port = -1
        command = [
            "ec2",
            "authorize-security-group-ingress",
            "--region",
            region,
            "--group-id",
            group_id,
            "--protocol",
            protocol,
            "--port",
            str(port),
            "--cidr",
            cidr,
        ]
        if aws(command) is None:
            aws(["ec2", "delete-security-group", "--region", region, "--group-id", group_id])
            return None
    return group_id


def _run_billing(args: dict[str, Any]) -> tuple[str, str]:
    if not REAL:
        return "ok", "Billing query is read-only (Cost Explorer is unavailable in LocalStack)"

    today = date.today()
    start = str(args.get("time_period_start") or today.replace(day=1).isoformat())
    end = str(args.get("time_period_end") or today.isoformat())
    granularity = str(args.get("granularity") or "MONTHLY")
    metrics = args.get("metrics") or ["UnblendedCost"]
    if not isinstance(metrics, list) or not metrics:
        metrics = ["UnblendedCost"]

    command = [
        "ce",
        "get-cost-and-usage",
        "--time-period",
        f"Start={start},End={end}",
        "--granularity",
        granularity,
        "--metrics",
        *[str(metric) for metric in metrics],
    ]
    if args.get("group_by_service") is True:
        command += ["--group-by", "Type=DIMENSION,Key=SERVICE"]

    if aws(command) is None:
        return "error", "Cost Explorer query failed"
    return "ok", "Billing query executed"


def describe_actions(name: str, args: dict[str, Any]) -> list[str]:
    """Return human-readable actions for a dry-run preview."""
    if name == "create_ec2_instance":
        actions: list[str] = []
        rules = args.get("security_group_rules") or []
        if rules:
            rendered = ", ".join(
                f"{rule.get('protocol', 'tcp')}/{rule.get('port', '?')} "
                f"from {rule.get('cidr', '0.0.0.0/0')}"
                for rule in rules
                if isinstance(rule, dict)
            )
            actions.append(f"create a security group with inbound rules: {rendered}")
        try:
            actions.append(" ".join(build_run_instances_cmd(args)))
        except (KeyError, TypeError, ValueError):
            actions.append("run-instances (invalid arguments)")
        return actions
    if name == "restart_database":
        try:
            return [" ".join(build_reboot_db_cmd(args))]
        except (KeyError, TypeError, ValueError):
            return ["reboot-db-instance (invalid arguments)"]
    if name == "get_billing_alert":
        return ["Cost Explorer get-cost-and-usage (real AWS only)"]
    return []


# ── Direct inference (lazy ML runtime) ──────────────────────────────────
def _offload_dir() -> str:
    """Return the CPU offload folder for the LoRA adapter."""
    return os.environ.get("ARC_OPS_OFFLOAD_DIR") or str(
        Path(tempfile.gettempdir()) / "arcops-offload"
    )


_model: Any = None
_tokenizer: Any = None


def _load_runtime(model_cfg: ModelConfig) -> tuple[Any, Any]:
    """Lazily import torch/transformers/peft and load the quantized model."""
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    except (ImportError, OSError) as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Model inference requires the ML extras, which are not installed.\n"
            "Install them with:  pip install 'cloudops-fc[train]'"
        ) from exc

    adapter = model_cfg.require_adapter()
    print(f"* Loading {model_cfg.key} model (first time ~30s)...")
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_cfg.name,
        quantization_config=bnb,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model = PeftModel.from_pretrained(model, adapter, offload_folder=_offload_dir())
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(model_cfg.name)
    tokenizer.pad_token = tokenizer.eos_token
    _model, _tokenizer = model, tokenizer
    return model, tokenizer


def load_model(model_cfg: ModelConfig | None = None) -> tuple[Any, Any]:
    """Load (or return the cached) model and tokenizer."""
    return _load_runtime(model_cfg or resolve_model_config())


def infer(
    prompt: str,
    model_cfg: ModelConfig,
    max_new_tokens: int = MAX_NEW_TOKENS,
) -> dict[str, Any]:
    """Convert a natural-language prompt into a tool-call JSON dict."""
    model, tokenizer = _load_runtime(model_cfg)
    import torch

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    inputs = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
    ).to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            inputs.input_ids,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    reply = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
    ).strip()
    try:
        return cast(dict[str, Any], json.loads(reply))
    except json.JSONDecodeError:
        return {"error": "invalid JSON", "raw": reply}
