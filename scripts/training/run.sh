#!/usr/bin/env bash
# ===========================================================================
# run.sh — QLoRA Training Pipeline Launcher (WSL2)
# ===========================================================================
#
# Reproducible entrypoint for the full training pipeline on WSL2 (Ubuntu).
#
# Usage:
#   ./scripts/training/run.sh                    # full pipeline
#   ./scripts/training/run.sh --smoke            # smoke test only
#   ./scripts/training/run.sh --config path.yaml # custom config
#
# Prerequisites (WSL2):
#   - uv installed (via pipx or curl)
#   - CUDA 12.8 toolkit (for sm_120 / Blackwell)
#   - git, rsync installed
#
# Environment variables:
#   RSYNC_DEST   Target directory on WSL2 native fs (default: ~/fine_tuning_model)
# ===========================================================================

set -euo pipefail

# ---- Configurable defaults ------------------------------------------------
RSYNC_DEST="${RSYNC_DEST:-$HOME/fine_tuning_model}"
CONFIG="scripts/training/default_config.yaml"
SMOKE_ONLY=false

# ---- Argument parsing -----------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --smoke)
            SMOKE_ONLY=true
            shift
            ;;
        --config)
            CONFIG="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--smoke] [--config path]"
            echo ""
            echo "  --smoke       Run smoke test only, skip training and eval"
            echo "  --config      Path to YAML config (default: $CONFIG)"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--smoke] [--config path]"
            exit 1
            ;;
    esac
done

# ---- WSL2 setup -----------------------------------------------------------
echo "=== [1/5] Syncing project to WSL2 native filesystem ==="
rsync -av --delete \
    --exclude .venv \
    --exclude __pycache__ \
    --exclude .git \
    --exclude checkpoints \
    --exclude '*.pyc' \
    ./ "$RSYNC_DEST/"

cd "$RSYNC_DEST"

echo "=== [2/5] Installing dependencies ==="
uv sync --extra train

# ---- Smoke test (gate) ---------------------------------------------------
echo "=== [3/5] Running smoke test ==="
uv run python scripts/training/smoke_test.py

if [[ "$SMOKE_ONLY" == true ]]; then
    echo ""
    echo "=== Smoke test PASSED — exiting (--smoke mode) ==="
    exit 0
fi

# ---- Training -------------------------------------------------------------
echo "=== [4/5] Starting QLoRA training ==="
uv run python scripts/training/train.py --config "$CONFIG"
TRAIN_EXIT=$?

if [[ $TRAIN_EXIT -ne 0 ]]; then
    echo "ERROR: Training failed with exit code $TRAIN_EXIT"
    exit $TRAIN_EXIT
fi

# ---- Evaluation -----------------------------------------------------------
echo "=== [5/5] Running evaluation ==="
uv run python scripts/training/eval.py --checkpoint "$RSYNC_DEST/checkpoints/final"

echo ""
echo "=== Training pipeline complete ==="
echo "  Config:      $CONFIG"
echo "  Output:      $RSYNC_DEST/checkpoints/"
echo "  Eval report: $RSYNC_DEST/checkpoints/eval_report.json"
