"""ArcOps exec — NL → JSON → LocalStack. End-to-end demo.

Default target is LocalStack (safe sandbox). Real AWS requires BOTH the
``--real`` flag AND ``ARC_OPS_REAL=1`` in the environment, plus an explicit
interactive confirmation — never run against real AWS by accident.

Inference and execution live in ``cloudops_fc.core``; this module only
provides the command-line workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT_ROOT / "src"
for _p in (str(_PROJECT_ROOT), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from cloudops_fc.core import (  # noqa: E402
    describe_actions,
    execute_tool_call,
    infer,
)
from cloudops_fc.models import resolve_model_config  # noqa: E402
from cloudops_fc.safety import check  # noqa: E402


def _configure_stdio() -> None:
    """Make stdout/stderr UTF-8 on Windows consoles (cp1252 can't encode →)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _confirm_action(message: str) -> bool:
    return input(f"  {message} (y/N): ").strip().lower() == "y"


def _confirm_real_aws() -> bool:
    """Require an explicit interactive confirmation for real-AWS actions."""
    answer = input(
        "  WARNING: this targets REAL AWS and may incur real costs.\n"
        "  Type 'yes' to confirm: "
    ).strip().lower()
    return answer == "yes"


def main(argv: list[str] | None = None) -> int:
    """Run the exec demo. Returns a process exit code."""
    _configure_stdio()
    parser = argparse.ArgumentParser(
        description="ArcOps exec — NL → AWS tool call (LocalStack by default)"
    )
    parser.add_argument("prompt", nargs="?", help="Natural language instruction")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute against LocalStack (requires Docker)",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help=(
            "Target REAL AWS. Requires ARC_OPS_REAL=1 in the environment "
            "and an interactive confirmation."
        ),
    )
    args = parser.parse_args(argv)

    if not args.prompt:
        parser.print_help()
        return 0

    if args.real and os.environ.get("ARC_OPS_REAL", "") != "1":
        print(
            "  ERROR: --real requires the explicit environment flag "
            "ARC_OPS_REAL=1 (protects against accidental real-AWS use)."
        )
        return 2

    print(f"\n  > {args.prompt}")
    print("\n  ... Generating tool call...")
    try:
        tool_call = infer(args.prompt, resolve_model_config())
    except RuntimeError as exc:
        print(f"  X Error: {exc}")
        return 1

    if "error" in tool_call:
        print(f"  X Error: {tool_call['error']}")
        return 1

    name = tool_call.get("name", "?")
    arguments = tool_call.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}
    print(f"  => Tool: {name}")
    print(f"     Args: {json.dumps(arguments, ensure_ascii=False)}")

    safety = check(name, arguments, env="development")
    for warning in safety.warnings:
        print(f"  {warning}")
    for error in safety.errors:
        print(f"  {error}")
    if safety.blocked or not safety.passed:
        print("  X Blocked by safety policy")
        return 1

    target = "REAL AWS" if args.real else "LocalStack"
    actions = describe_actions(name, arguments)
    print(f"\n  OK Planned actions against {target}:")
    for action in actions:
        print(f"     {action}")

    if args.real and not _confirm_real_aws():
        print("\n  Cancelled — no action executed.")
        return 0

    if args.live or args.real:
        confirm = (lambda _message: True) if args.real else _confirm_action
        print(f"\n  ... Executing against {target}...")
        status, message = execute_tool_call(
            name,
            arguments,
            confirm_callable=confirm,
            env="development",
            verbose=False,
        )
        print(f"  [{status}] {message}")
        if status != "ok":
            if not args.real:
                print("\n  Tip: make sure LocalStack is running:")
                print("     docker run -d --rm -p 4566:4566 localstack/localstack:3.0")
            return 1
        return 0

    print(f"\n  Tip: to execute: python -m app.exec --live \"{args.prompt}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
