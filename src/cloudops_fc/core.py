"""ArcOps shared engine — the single core behind the CLI and the TUI.

This module is the one place where inference and AWS execution live:

- ``infer()`` + ``_load_runtime()`` convert natural language into a JSON
  tool call. The ML stack (torch/transformers/peft) is imported lazily so
  the module itself imports without the ML extras installed.
- The AWS layer (``aws``, ``ls_check``, ``get_all``, ``act``, ``tag_it``,
  ``create``) executes tool calls against LocalStack by default, or real
  AWS when ``ARC_OPS_REAL=1``. Destructive actions require an explicit
  confirmation (a ``confirm_callable``); when none is provided they are
  refused.

Both the CLI face (``cloudops_fc.cli``) and the TUI (``app.tui``) import
from here — there is no duplicated logic and no external "model server"
to wait on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cloudops_fc.models import ModelConfig, resolve_model_config
from cloudops_fc.safety import check

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
            AWS_BASE + args, capture_output=True, text=True, timeout=15,
            env=ENV, cwd=PROJECT_ROOT,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        pass
    return None


def ls_check() -> bool:
    """Return True when LocalStack's health endpoint answers 200."""
    for _ in range(5):  # 5 retries, 1s apart
        try:
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "http://localhost:4566/_localstack/health"],
                capture_output=True, text=True, timeout=5,
            )
            if r.stdout.strip() == "200":
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def get_all() -> list[dict]:
    """List EC2 instances and RDS databases as dashboard rows."""
    items: list[dict] = []
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
    item: dict,
    cmd: str,
    confirm_callable: Callable[[str], bool] | None = None,
) -> None:
    """Run a resource action; destructive actions require confirmation.

    ``confirm_callable`` is invoked with a message and must return True to
    proceed. When a destructive action needs confirmation and no callable
    was provided, the action is refused.
    """
    destructive = cmd in ("terminate-instances", "delete-db-instance") or item["t"] == "RDS"
    if destructive:
        label = f"TERMINATE {item['id']}" if item["t"] == "EC2" else f"DELETE {item['id']}"
        target = "REAL AWS" if REAL else "LocalStack"
        if confirm_callable is None:
            print(f"  Refused: confirmation required for {label} on {target}")
            return
        if not confirm_callable(f"{label} on {target}?"):
            print(f"  Cancelled: {item['id']}")
            return
    if item["t"] == "EC2":
        aws(["ec2", cmd, "--instance-ids", item["id"]])
    else:
        aws(["rds", "delete-db-instance", "--db-instance-identifier",
             item["id"], "--skip-final-snapshot"])


def tag_it(item: dict, key: str, val: str) -> None:
    """Replace all tags on an instance with a single key/value pair."""
    r = aws(["ec2", "describe-instances", "--instance-ids", item["id"]])
    if r:
        for res in r.get("Reservations", []):
            for inst in res.get("Instances", []):
                for t in inst.get("Tags", []):
                    aws(["ec2", "delete-tags", "--resources", item["id"],
                         "--tags", f"Key={t['Key']}"])
    aws(["ec2", "create-tags", "--resources", item["id"],
         "--tags", f"Key={key},Value={val}"])


def create(
    prompt: str,
    confirm_callable: Callable[[str], bool] | None = None,
) -> tuple[str, str]:
    """Generate a tool call from a prompt, safety-check it, and execute.

    Runs inference in-process (the model loads once, ~30s on first call),
    then validates the result with the canonical safety layer. Returns a
    ``(status, message)`` pair where status is one of ``ok``, ``blocked``,
    ``cancelled``, or ``error``.

    ``confirm_callable`` is invoked for actions that require approval
    (disruptive actions, or any action in real-AWS mode). When approval is
    required and no callable was provided, the action is refused.
    """
    if not REAL and not ls_check():
        return "error", "LocalStack not running. Press [l] to launch."

    try:
        result = infer(prompt, resolve_model_config())
    except RuntimeError as exc:
        return "error", str(exc)

    name = result.get("name", "")
    args = result.get("arguments", {})
    if not name:
        return "error", "Model returned no tool call"

    safety = check(name, args, env="development")
    print("\n  -- Safety Check --")
    for w in safety.warnings:
        print(f"  {w}")
    for e in safety.errors:
        print(f"  {e}")
    print()

    if safety.blocked or not safety.passed:
        return "blocked", "Blocked by safety policy"

    if safety.requires_approval or REAL:
        if confirm_callable is None:
            return "cancelled", "Confirmation required but no confirm callback provided"
        target = "REAL AWS" if REAL else "LocalStack"
        if not confirm_callable(f"Approve this action on {target}?"):
            return "cancelled", "Cancelled"

    if name == "create_ec2_instance":
        r = aws(["ec2", "run-instances",
                 "--region", args["region"],
                 "--instance-type", args["instance_type"]])
        if r and isinstance(r, dict) and "Instances" in r:
            iid = r.get("Instances", [{}])[0].get("InstanceId", "?")
            cost_msg = f" (~${safety.estimated_cost:.0f}/mo)" if safety.estimated_cost else ""
            return "ok", f"Created {iid}{cost_msg}"
        return "error", "AWS command failed — LocalStack may be down"
    if name == "restart_database":
        r = aws(["rds", "reboot-db-instance",
                 "--db-instance-identifier", args["db_instance_identifier"],
                 "--region", args["region"]])
        if r is not None:
            return "ok", "Database rebooting"
        return "error", "AWS command failed — LocalStack may be down"
    if name == "get_billing_alert":
        return "ok", "Billing (read-only)"
    return "ok", f"JSON: {json.dumps(result)}"


# ── Direct inference (lazy ML runtime) ──────────────────────────────────
def _offload_dir() -> str:
    """Return the CPU offload folder for the LoRA adapter.

    Uses ``ARC_OPS_OFFLOAD_DIR`` when set, otherwise the platform temp dir,
    so it works on Windows and Linux without hardcoded paths.
    """
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
    except ImportError as exc:  # pragma: no cover - environment dependent
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


def infer(prompt: str, model_cfg: ModelConfig) -> dict[str, Any]:
    """Convert a natural-language prompt into a tool-call JSON dict."""
    model, tokenizer = _load_runtime(model_cfg)  # imports torch; raises clear error if missing
    import torch  # guaranteed available after a successful runtime load

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
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    reply = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
    ).strip()
    try:
        return json.loads(reply)
    except json.JSONDecodeError:
        return {"error": "invalid JSON", "raw": reply}
