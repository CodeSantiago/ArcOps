# Design: Project Scaffolding

## Technical Approach

Bootstrap the repository as an installable Python package (`cloudops_fc`) under uv-managed Python 3.12, with JSON schema validation as the first capability. Dependencies are minimal and pure-Python (`jsonschema` runtime; `pytest`, `pytest-cov`, `ruff`, `mypy` dev). The scaffold produces no binaries, no GPU code, and no network-bound services — every line of code is testable in isolation on Windows or WSL2.

Architecture: a **flat validation module** (`cloudops_fc.schemas`) that loads JSON Schema documents as package data and delegates validation to the `jsonschema` library. Tests exercise validation against the Draft 2020-12 meta-schema, valid payloads, and malformed inputs.

## Architecture Decisions

### Decision: uv for Environment Management

| Option | Tradeoff |
|--------|----------|
| **uv** | Fast resolver; manages Python interpreters (`uv python install 3.12`); single-source truth in `pyproject.toml` + `uv.lock`; PEP 735 dependency groups |
| pip + venv | No lockfile; no managed Python; slow with large ML wheels |
| Poetry | PyTorch index-priority issues; no Python version management |

**Choice**: uv. Decisive factor: manages Python 3.12 alongside system 3.14 without OS-level changes. Must install uv as a prerequisite via winget (fallback: standalone script).

### Decision: src-layout with Package Data Schemas

| Option | Tradeoff |
|--------|----------|
| **src-layout** | Tests install the package; no CWD-relative imports; schema files bundled as package data accessible via `importlib.resources` |
| flat layout | Simpler to start; tests can pass against uninstalled code — fragile |

**Choice**: src-layout. Guarantees that tests run against the *installed* package, matching inference-time behavior. JSON schemas live under `src/cloudops_fc/schemas/` as `.json` files, loaded via `importlib.resources.files()` — no `__file__`-based path hacks.

### Decision: jsonschema Library

**Choice**: `jsonschema` (PyPI). Pure-Python, no compiled extensions, supports Draft 2020-12 natively. Single runtime dependency. Alternatives (`fastjsonschema`, manual validation) would save microseconds but add zero architectural value.

### Decision: Test/Meta-Schema Strategy

**Choice**: Validate every schema file against the Draft 2020-12 meta-schema as a fixture-based test. The meta-schema is loaded from `jsonschema`'s built-in references — no external downloads. This catches structural schema errors before any payload reaches the validator.

## Data Flow: Schema Validation

```
┌──────────────────┐     importlib.resources      ┌──────────────┐
│  schema JSON      ──────────────────────────────→  JSON Schema  │
│  (package data)   │                              │  (dict)      │
└──────────────────┘                              └──────┬───────┘
                                                          │
                                                          ▼
┌──────────────────┐     validate(instance, schema)  ┌──────────────┐
│  user payload     ──────────────────────────────→  jsonschema    │
│  (NL→JSON dict)  │     against Draft 2020-12       │  validator    │
└──────────────────┘                              └──────┬───────┘
                                                          │
                                                          ▼
                                                  ┌──────────────┐
                                                  │  Validation   │
                                                  │  Result       │
                                                  │  (pass/fail   │
                                                  │   + errors)   │
                                                  └──────────────┘
```

Every validation exercise in this change follows this path. No network, no disk I/O at test time — the schema is loaded from the installed package tree.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Create | Package metadata, deps, uv config, ruff/mypy/pytest/coverage config |
| `.python-version` | Create | Pins uv to Python 3.12 |
| `src/cloudops_fc/__init__.py` | Create | Package marker (empty or docstring) |
| `src/cloudops_fc/py.typed` | Create | PEP 561 marker for mypy |
| `src/cloudops_fc/schemas/__init__.py` | Create | Package marker for schema subpackage |
| `src/cloudops_fc/schemas/create_ec2_instance.json` | Create | Seed JSON Schema for EC2 instance creation |
| `tests/conftest.py` | Create | Shared fixtures (schema loader, valid payload) |
| `tests/unit/test_schema_validation.py` | Create | Meta-schema, valid-payload, malformed-payload tests |
| `.gitignore` | Create | Python/ML/tooling ignores |
| `.gitattributes` | Create | `* text=auto eol=lf` |
| `.env.example` | Create | Template for env secrets |
| `README.md` | Create | Project overview + setup instructions |
| `openspec/config.yaml` | Modify | `testing.runner: pytest`, `coverage_threshold: 80`, `strict_tdd: true` |

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Schema meta-conformance | Load each `.json` file under schemas/; validate against Draft 2020-12 meta-schema |
| Unit | Valid payload acceptance | Construct valid EC2 payload dict; assert passes schema (R2) |
| Unit | Malformed rejection | Missing field, wrong type, extra field — each asserts failure with error description (R3) |
| Integration | Schema loadability | Assert `importlib.resources.files("cloudops_fc.schemas").joinpath(...).read_text()` returns valid JSON (R4) |
| Import | Package importability | `python -c "import cloudops_fc"` exit 0 (R5) |
| Quality | Lint + types | `ruff check` zero errors (R7), `mypy src/cloudops_fc/` zero errors (R7) |

Coverage floor: 80% (R6). The code surface is small — schema loading, validation function, fixtures — so 80% is achievable from the first test run.

## Interfaces / Contracts

```python
# src/cloudops_fc/schemas/__init__.py (conceptual signature)

def load_schema(name: str) -> dict:
    """Load a JSON Schema by its stem name (e.g. 'create_ec2_instance').
    Returns the parsed schema dict.
    Raises FileNotFoundError if the schema does not exist as package data.
    """

def validate_payload(schema: dict, payload: dict) -> list[str]:
    """Validate a payload dict against a schema dict.
    Returns a list of error messages (empty list = valid).
    """
```

## Migration / Rollout

No migration required — greenfield project.

## Open Questions

None. All technical questions were resolved during exploration.
