#!/usr/bin/env python3
"""ArcOps CLI — Natural language → AWS JSON tool calls. 100% local.

Canonical entry point installed as the ``arcops`` console command
(see ``[project.scripts]`` in ``pyproject.toml``).

Works without a GPU for metadata commands (``tools``, ``--help``).
Prompt inference requires the ML extra and a local model:

    pip install 'cloudops-fc[train]'
    arcops "Create a t3.micro server in us-east-1 with port 80"

Environment overrides:

- ``ARC_OPS_MODEL``       ``7b`` (default) or ``1.5b``
- ``ARC_OPS_ADAPTER``     HuggingFace adapter repo ID (default ``CodeSantiago/arcops`` for 7B)
- ``ARC_OPS_OFFLOAD_DIR`` CPU offload folder for the adapter (default: system temp)

The 1.5B model has no public adapter by default — set ``ARC_OPS_ADAPTER``
to your own fine-tuned adapter repo ID to use ``1.5b``.

Inference lives in the shared engine (``cloudops_fc.core``); this module
only wires it to the terminal. ``arcops tui`` launches the dashboard.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from cloudops_fc.core import MAX_NEW_TOKENS, SYSTEM_PROMPT, infer
from cloudops_fc.models import ModelConfig, resolve_model_config
from cloudops_fc.safety import check

__all__ = [
    "MAX_NEW_TOKENS",
    "SYSTEM_PROMPT",
    "infer",
    "main",
]


def _configure_stdio() -> None:
    """Make stdout/stderr UTF-8 on Windows consoles (cp1252 can't encode →)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


# ── Subcommands ────────────────────────────────────────────────────────
EVAL_CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("Create a t3.micro server in us-east-1", "create_ec2_instance",
     {"region": "us-east-1", "instance_type": "t3.micro"}),
    ("Restart the production database in us-west-2", "restart_database",
     {"db_instance_identifier": "production", "region": "us-west-2"}),
    ("How much did we spend this month?", "get_billing_alert",
     {"granularity": "MONTHLY"}),
    ("Create a server with port 80 open", "create_ec2_instance",
     {"region": "us-east-1", "instance_type": "t3.micro",
      "security_group_rules": [{"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"}]}),
    ("Restart analytics-db with failover", "restart_database",
     {"db_instance_identifier": "analytics-db", "region": "us-east-1",
      "force_failover": True}),
]


def _cmd_eval(model_cfg: ModelConfig) -> int:
    """Run the quick accuracy evaluation over the built-in cases.

    Each case runs inference exactly once; tool accuracy compares the
    predicted tool name against the expected tool name.
    """
    print("\n  ArcOps Quick Evaluation\n")
    exact = 0
    correct_tools = 0
    total_fields = 0
    correct_fields = 0
    for prompt, exp_tool, exp_args in EVAL_CASES:
        try:
            result = infer(prompt, model_cfg)
        except RuntimeError as exc:
            print(f"  XX {exc}")
            return 1
        name = result.get("name")
        args = result.get("arguments", {})
        tool_ok = name == exp_tool
        correct_tools += 1 if tool_ok else 0
        field_ok = sum(1 for k, v in exp_args.items() if args.get(k) == v)
        field_total = len(exp_args)
        exact_match = tool_ok and field_ok == field_total
        exact += 1 if exact_match else 0
        total_fields += field_total
        correct_fields += field_ok
        print(
            f"  {'OK' if exact_match else 'XX'} tool={name}  "
            f"fields={field_ok}/{field_total}  {prompt[:50]}"
        )
    n = len(EVAL_CASES)
    print(f"\n  Tool accuracy: {correct_tools}/{n} = {correct_tools / n:.0%}")
    print(
        "  Field accuracy: "
        f"{correct_fields}/{total_fields} = {correct_fields / total_fields:.1%}"
    )
    print(f"  Exact match: {exact}/{n} = {exact / n:.0%}")
    return 0


def _cmd_tools() -> int:
    """List the supported AWS tools."""
    print("\n  EC2 — Create a virtual server")
    print("  RDS — Restart a database")
    print("  Billing — Get cost and usage data\n")
    return 0


def _cmd_tui() -> int:
    """Launch the terminal dashboard (app.tui), importing it lazily."""
    from pathlib import Path

    # Make sure the repo root is importable so ``app`` resolves even when
    # the TUI is launched from an installed console script outside the repo.
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from app.tui import main as tui_main
    except ImportError as exc:  # pragma: no cover - environment dependent
        print(f"Error: cannot import the TUI: {exc}")
        return 1

    tui_main()
    return 0


# ── CLI ────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    """Run the ArcOps CLI. Returns a process exit code."""
    _configure_stdio()
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in ("-h", "--help"):
        print("\n  ArcOps — NL → AWS tool calls\n")
        print('  arcops "Create a t3.micro server"    Generate tool call')
        print('  arcops --json "..."                  Raw JSON output')
        print('  arcops --light "..."                 Use the 1.5B model')
        print("  arcops --eval                        Quick accuracy check")
        print("  arcops tools                         List supported tools")
        print("  arcops tui                          Launch the terminal dashboard")
        print("\n  Examples:")
        print('  arcops "Create a t3.micro server in us-east-1"')
        print('  arcops "How much did we spend this month?"')
        print('  arcops --json "Restart the production database"')
        print("\n  Requires the ML extras for inference:")
        print("  pip install 'cloudops-fc[train]'")
        print("\n  The 1.5B model needs an explicit adapter:")
        print("  set ARC_OPS_ADAPTER to your fine-tuned 1.5B adapter repo ID.")
        return 0

    if args[0] == "tui":
        return _cmd_tui()

    if args[0] == "tools":
        return _cmd_tools()

    key = "1.5b" if "--light" in args else None
    try:
        model_cfg = resolve_model_config(key=key)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}")
        return 2

    if "--eval" in args:
        return _cmd_eval(model_cfg)

    flags = {"--json", "--light"}
    prompt = " ".join(a for a in args if a not in flags)
    if not prompt.strip():
        print("Error: no prompt provided. Try: arcops \"Create a t3.micro server\"")
        return 2

    try:
        result = infer(prompt, model_cfg)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1

    if "--json" in args:
        print(json.dumps(result, ensure_ascii=False))
        return 0

    name = result.get("name", "")
    call_args = result.get("arguments", {})
    result_check = check(name, call_args)

    print(f"\n  > {prompt}")
    print(f"  => {json.dumps(result, ensure_ascii=False)}")
    if result_check.warnings or result_check.errors:
        print("\n  -- Safety --")
        for w in result_check.warnings:
            print(f"  {w}")
        for e in result_check.errors:
            print(f"  {e}")
        if result_check.blocked:
            print("  Action BLOCKED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
