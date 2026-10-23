# Contributing

Thanks for taking a look. ArcOps is a small, opinionated codebase; keep changes
focused and explain the why.

## Setup

```bash
git clone https://github.com/CodeSantiago/ArcOps.git
cd ArcOps
uv sync --extra dev
uv run pytest -q
```

The default suite does not need PyTorch, CUDA, LocalStack or AWS.

If `uv sync` fails on Windows with an "Access is denied" error, the project or
`.venv` is probably inside a synced folder (OneDrive, Dropbox). Keep the
virtualenv outside the synced folder or exclude `.venv` from sync; the synced
folder can lock package files during upgrades.

For the full stack:

```bash
uv sync --extra train --extra tui --extra api
```

On Windows, replace the CPU torch wheel with the CUDA build:

```powershell
uv pip install --reinstall torch --index-url https://download.pytorch.org/whl/cu130
```

## Checks

```bash
uv run pytest -q
uv run pytest -q --cov=cloudops_fc --cov-report=term
uv run ruff check src/ cloudops.py app/ tests/ scripts/
uv run mypy src/cloudops_fc
```

All four should pass before a pull request.

## Pull requests

- Use conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`).
- Add or update tests for behavior changes.
- Keep the engine contract intact: interfaces call `cloudops_fc.core`; do not
  duplicate inference or AWS logic.
- Update the README, docs or schemas when the public behavior changes.
- Never commit credentials, `.env` files, model weights or generated datasets.

## Adding a tool

1. Add a JSON Schema under `src/cloudops_fc/schemas/`.
2. Register it in `safety.TOOL_SCHEMAS` and the schema tests.
3. Implement execution and a dry-run description in `core.py`.
4. Add a command-builder test and a safety test.
5. Update the README tool table and, if the model should learn it, the dataset
   generator.

## Adding a model

1. Extend `cloudops_fc.models.resolve_model_config()`.
2. Add a config under `scripts/training/`.
3. Keep the adapter configurable via `ARC_OPS_ADAPTER`.
4. Report evaluation results with the split mode next to the score.

## Code style

- Python 3.12+, type hints, `from __future__ import annotations`.
- Ruff with the repository configuration; line length 100.
- Prefer small functions and explicit data structures.
- No comments that restate the code; explain tradeoffs and non-obvious choices.
