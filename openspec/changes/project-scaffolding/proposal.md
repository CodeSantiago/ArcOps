# Proposal: Project Scaffolding

## Intent

Bootstrap the greenfield repository into a working Python dev environment: uv-managed Python 3.12 with src-layout package `cloudops_fc`, JSON schema validation test suite, lint/type tooling, git foundation, and quality gates. This is the foundational change that enables every subsequent SDD change.

## Scope

### In Scope
1. uv install + Python 3.12 pin + `pyproject.toml` declaring core deps (`jsonschema`) and dev deps (`pytest`, `pytest-cov`, `ruff`, `mypy`)
2. src-layout skeleton: `src/cloudops_fc/` with `__init__.py`, `py.typed`, `schemas/` package data
3. Seed schema `create_ec2_instance` as package data, readable via `importlib.resources`
4. First test suite: schema meta-validation, valid example, malformed payloads
5. ruff + mypy config in `pyproject.toml` (single source of truth)
6. Git bootstrap: `git init`, `.gitignore` (ML-aware), `.gitattributes` (`eol=lf`), `.env.example`, `README.md`
7. `openspec/config.yaml` update: test/coverage commands, `coverage_threshold: 80`, `strict_tdd: true`

### Out of Scope
- ML stack (torch, transformers, peft, trl, bitsandbytes, datasets, accelerate) — deferred to training change
- GPU validation or CUDA setup
- pre-commit hooks
- CI/CD pipeline
- Training, evaluation, or inference code

## Capabilities

### New Capabilities
- `schema-validation`: JSON Schema validation of function-calling tool definitions. Covers meta-schema conformance, valid NL→JSON examples, and rejection of malformed payloads.

### Modified Capabilities
None — no existing specs to modify.

## Approach

Install uv (winget, fallback standalone); `uv python install 3.12`; `uv sync` resolves all deps. Package scaffold is minimal Python files under src-layout. `pyproject.toml` is the single source of truth for deps, tool config, and build metadata. Tests use pytest with cov configured inline. Schema validation tests exercise pure logic — no GPU, no network.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `pyproject.toml` | New | Packaging, deps, tool config |
| `src/cloudops_fc/` | New | Package skeleton + schemas |
| `tests/` | New | pytest layout + validation tests |
| `.gitignore` | New | ML-aware ignores |
| `.gitattributes` | New | Cross-platform line endings |
| `.env.example` | New | Env template |
| `README.md` | New | Project overview |
| `openspec/config.yaml` | Modified | Testing config, strict_tdd |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| OneDrive I/O churn on sync | Low | .gitignore excludes venvs, data, models |
| uv winget install fails | Low | Fallback to standalone installer |
| uv-managed 3.12 vs system 3.14 gaps | Low | All deps pure Python; no ABI issues |

## Rollback Plan

Before first commit: delete created files, no action needed. After first commit: `git reset --hard HEAD~1` and delete untracked files. Rollback of uv: `winget uninstall uv` or delete standalone binary.

## Dependencies

None. uv is installed as part of this change.

## Success Criteria

- [ ] `uv run pytest -v --cov=cloudops_fc` passes with >=80% coverage
- [ ] `uv run ruff check src/ tests/` passes (0 errors)
- [ ] `uv run mypy src/cloudops_fc/` passes (0 errors)
- [ ] `uv run python -c "import cloudops_fc"` succeeds
- [ ] `git log --oneline` shows initial commit with scaffold only
