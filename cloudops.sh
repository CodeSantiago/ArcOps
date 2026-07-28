#!/usr/bin/env bash
# ArcOps — Natural language → AWS JSON tool calls
#   arcops "prompt"          → JSON tool call
#   arcops exec "prompt"     → Execute against LocalStack
#   arcops --json "prompt"   → Raw JSON output
#   arcops serve             → Persistent server
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$1" = "exec" ]; then
    shift
    uv run python "$DIR/app/exec.py" "$@"
else
    uv run python "$DIR/cloudops.py" "$@"
fi
