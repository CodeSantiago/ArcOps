# CloudOps Function Calling (cloudops-fc)

NL-to-JSON schema validation for AWS API calls. Turn natural language
instructions into structured, validated function-calling payloads.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) >= 0.5 (installs Python 3.12 automatically)
- Git

## Setup

```bash
# Install Python 3.12 and create virtual environment
uv sync --dev

# Activate the environment (PowerShell)
.venv\Scripts\activate

# Verify the package is importable
uv run python -c "import cloudops_fc; print(cloudops_fc.__version__)"
```

## Run Tests

```bash
# Full test suite with coverage
uv run pytest --cov=cloudops_fc --cov-report=term-missing

# Run only unit tests
uv run pytest tests/unit/ -v
```

## Quality Gates

```bash
# Lint
uv run ruff check src/cloudops_fc/ tests/

# Type check
uv run mypy src/cloudops_fc/
```

## Project Structure

```
src/cloudops_fc/          # Package source (src-layout)
├── __init__.py
├── py.typed              # PEP 561 marker
└── schemas/              # JSON Schema definitions
    ├── __init__.py       # load_schema() / validate_payload()
    └── create_ec2_instance.json

tests/
├── conftest.py           # Shared fixtures
└── unit/
    └── test_schema_validation.py
```

## Tech Stack

- **Runtime**: Python 3.12 (managed by uv), `jsonschema`
- **Dev**: pytest, pytest-cov, ruff, mypy
- **Architecture**: src-layout, pure-Python, zero ML deps
