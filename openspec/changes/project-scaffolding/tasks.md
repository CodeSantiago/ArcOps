# Tasks: Project Scaffolding

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~300 (all additions, 0 deletions) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | single-pr |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: single-pr
400-line budget risk: Low

## Phase 1: Prerequisites

- [ ] 1.1 Install uv via winget (fallback: standalone script); verify `uv --version`
- [ ] 1.2 Run `git init` in project root

## Phase 2: Foundation

- [ ] 2.1 Create `.python-version` pinning `3.12`
- [ ] 2.2 Create `pyproject.toml` — package metadata, uv config, deps (jsonschema; dev: pytest, pytest-cov, ruff, mypy), tool configs
- [ ] 2.3 Create `src/cloudops_fc/__init__.py` (package marker)
- [ ] 2.4 Create `src/cloudops_fc/py.typed` (PEP 561 marker)

## Phase 3: Schema + Validation Logic

- [ ] 3.1 Create `src/cloudops_fc/schemas/__init__.py` with `load_schema(name)` and `validate_payload(schema, payload)` stubs
- [ ] 3.2 Create `src/cloudops_fc/schemas/create_ec2_instance.json` (Draft 2020-12 schema for EC2 instance creation)

## Phase 4: TDD (RED → GREEN)

- [ ] 4.1 Create `tests/conftest.py` — fixtures: schema loader, valid payload, invalid payloads
- [ ] 4.2 Create `tests/unit/test_schema_validation.py` — tests for meta-conformance, valid payload, missing field, wrong type, extra field, schema loadability
- [ ] 4.3 Run `uv run pytest` — tests fail (RED, stubs return no-op)
- [ ] 4.4 Implement `load_schema()` using `importlib.resources` and `validate_payload()` using `jsonschema.validate`
- [ ] 4.5 Run `uv run pytest --cov=cloudops_fc` — all pass, coverage >=80%

## Phase 5: Quality Gates

- [ ] 5.1 Run `uv run ruff check src/cloudops_fc/ tests/` — fix all issues
- [ ] 5.2 Run `uv run mypy src/cloudops_fc/` — fix all type errors

## Phase 6: Bootstrap Files + Commit

- [ ] 6.1 Create `.gitignore` (Python/ML/uv/venv/tooling ignores)
- [ ] 6.2 Create `.gitattributes` (`* text=auto eol=lf`)
- [ ] 6.3 Create `.env.example`
- [ ] 6.4 Create `README.md` (project overview, setup steps)
- [ ] 6.5 Update `openspec/config.yaml` — runner=pytest, quality tools, coverage_threshold=80, strict_tdd=true
- [ ] 6.6 `git add -A`; `git commit -m "feat: initial project scaffold"`

## Parallelization Opportunities

- Phase 1 tasks (1.1, 1.2) can run in parallel with each other
- Phase 2 tasks (2.1–2.4) are independent of each other
- Phase 6 tasks (6.1–6.5) are independent of each other
- All other phases are strictly sequential (Phase 3 → Phase 4 → Phase 5)

## Dependency Graph

```
Phase 1        Phase 2        Phase 3        Phase 4        Phase 5        Phase 6
(uv, git) ──→ (pyproject) ──→ (schemas) ──→ (tests TDD) ──→ (quality) ──→ (bootstrap)
```

## Risk Notes

- **uv installation**: winget may fail in restricted environments; standalone installer is verified fallback
- **pydantic vs jsonschema**: binding decisions listed "pydantic" but design analysis chose `jsonschema` — design is authoritative, no action needed
- **WSL2 compatibility**: all tooling tested in Windows PowerShell; WSL2 users may need `uv` WSL2 install path instead of winget
