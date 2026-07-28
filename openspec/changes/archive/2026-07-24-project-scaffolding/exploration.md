# Exploration: project-scaffolding

**Change**: project-scaffolding
**Date**: 2026-07-24
**Mode**: hybrid (Engram + OpenSpec)

## Current State

Greenfield — the working directory contains only `.atl/` and `openspec/`. No source code, no git repository, no packaging, no test tooling. Environment verified on 2026-07-24:

| Fact | Value | Implication |
| --- | --- | --- |
| OS | Windows (win32), PowerShell 5.1 | Scaffold must work on native Windows |
| Python | 3.14.6 (system) | Bleeding-edge; ecosystem margin favors pinning 3.12 |
| git | 2.54.0.windows.1 | Ready for `git init` |
| uv | NOT installed | Must be installed during this change (winget/standalone) |
| GPU | NVIDIA RTX 5070, 12 GB VRAM, driver 610.74 (CUDA 13.3) | Blackwell (sm_120) → torch needs cu128+ builds; 12 GB is tight for QLoRA 8B |
| WSL | WSL2 present, default distro Ubuntu-24.04 | Training-runtime question is settled: WSL2 is available NOW |
| Project path | Inside OneDrive (`...\OneDrive\Desktop\Proyectos\...`) | Sync churn / file-locking / I/O risk for venvs, datasets, checkpoints |

No ML libraries installed (torch, transformers, peft, trl, datasets, bitsandbytes — all verified absent during sdd-init). No pytest.

## Affected Areas

Greenfield — this change CREATES rather than modifies:

- `pyproject.toml` — packaging, dependencies, and all tool configuration (single source of truth)
- `uv.lock`, `.python-version` — reproducible environment
- `src/cloudops_fc/` — new package skeleton (src-layout)
- `tests/` — pytest layout plus the first unit tests (JSON schema validation)
- `.gitignore`, `.gitattributes`, `.env.example`, `README.md` — git bootstrap
- `openspec/config.yaml` — test/coverage commands filled in, `strict_tdd: false → true` (updated by this change's apply phase)

## Approaches

### 1. Packaging & dependency management

| Approach | Pros | Cons | Effort |
| --- | --- | --- | --- |
| **uv** (recommended) | Fastest resolver/installer (matters for multi-GB ML wheels later); manages Python versions (`uv python install 3.12`) — critical because system Python is 3.14; single `pyproject.toml` + `uv.lock`; PEP 735 dependency-groups for dev tooling; `[tool.uv.sources]` cleanly handles PyTorch's custom wheel index when the time comes; identical commands on Windows and WSL2 | One extra tool to install; younger than pip (learning curve is minimal) | Low |
| pip + venv | Zero new tooling; universally known | No lockfile without pip-tools; slow with large wheels; cannot manage Python interpreters (the 3.14 problem stays unsolved); manual PyTorch index juggling later | Low–Med |
| Poetry | Mature lockfile; good DX | Historically painful with PyTorch custom indexes (source-priority issues); slower resolver; does not manage Python versions | Med |

**Recommendation: uv.** The decisive feature is managed Pythons: `.python-version` + `uv python install 3.12` solves the bleeding-edge-system-Python problem without touching the OS install, and the same workflow works inside WSL2.

**Python pin: 3.12** (`requires-python = ">=3.12,<3.13"`). pytorch.org currently lists 3.10–3.14 support, but the compiled corners of the ML ecosystem (xformers, flash-attention builds, CUDA tooling) lag new CPython releases. 3.12 is the compatibility sweet spot and costs nothing under uv.

### 2. Directory layout

| Approach | Pros | Cons |
| --- | --- | --- |
| **src-layout** (recommended) | Tests run against the INSTALLED package, not CWD accidents; standard for distributable packages; clean separation of code vs data vs SDD artifacts | Slightly more boilerplate; needs editable install (`uv sync` handles it) |
| flat | Zero ceremony | CWD-dependent imports; tests can pass against uninstalled code; degrades once `scripts/`, `data/`, notebooks arrive |

Proposed tree (this change creates the skeleton; later changes fill it in):

```
fine_tuning_model/
├── .atl/                      # (existing) SDD local state
├── openspec/                  # (existing) SDD artifacts
├── src/
│   └── cloudops_fc/
│       ├── __init__.py
│       ├── py.typed
│       └── schemas/           # JSON Schema docs as package data + validator module
├── tests/
│   ├── conftest.py
│   ├── unit/                  # first: test_schema_validation.py
│   └── integration/           # empty for now
├── scripts/                   # future CLIs (dataset generation, smoke checks)
├── data/                      # gitignored — raw/processed datasets
├── models/                    # gitignored — base models, adapters, checkpoints
├── pyproject.toml
├── uv.lock
├── .python-version            # 3.12
├── .gitignore
├── .gitattributes             # * text=auto eol=lf
├── .env.example
└── README.md
```

Notes:

- JSON Schema documents live as **package data** under `src/cloudops_fc/schemas/`, read via `importlib.resources` — the same validation code ships with the package and is reusable at inference time. (Alternative: top-level `schemas/` for non-Python consumers — rejected; nothing external consumes them yet.)
- Package name `cloudops_fc` (CloudOps function calling): short, importable, descriptive.
- `data/` and `models/` are gitignored working directories; in WSL2 training runs they live OUTSIDE OneDrive (see §7).

### 3. Testing setup

- pytest + pytest-cov, configured entirely in `pyproject.toml` (`[tool.pytest.ini_options]`, `[tool.coverage.*]`).
- **First testable unit: JSON schema validation of tool definitions** — pure Python, no GPU, no network. Concretely: (a) every schema file in the package validates against the JSON Schema meta-schema; (b) a valid NL→JSON example passes; (c) malformed payloads (missing required field, wrong type, unexpected AWS action) fail. This directly implements the project convention "function-calling outputs MUST be validated against explicit JSON schemas."
- Coverage: `fail_under = 80` from day one. The scaffolding code is tiny and fully testable; starting high establishes the ratchet and legitimizes flipping `strict_tdd` to `true` after this change.
- `tests/unit/` vs `tests/integration/` split from the start; `conftest.py` at tests root.

### 4. Lint/type tooling

- **ruff** for lint + format (replaces flake8 + isort + black): line-length 100, target-version py312, rule sets `E, F, I, UP, B, SIM`. One tool, one config block in pyproject.toml.
- **mypy** in pragmatic ratcheting mode: `python_version = 3.12`, `disallow_untyped_defs = true` scoped to `cloudops_fc`, `ignore_missing_imports = true` for third-party (torch stubs arrive with the training change).
- Alternative considered: pyright/basedpyright — faster and friendlier with torch's dynamic typing. Either is acceptable; mypy keeps the classic default with config-in-pyproject. ruff is the non-negotiable half.
- No pre-commit framework in this change (defer); document the manual commands in README.

### 5. Git bootstrap

- `git init`; conventional commits from the first commit; initial commit contains scaffolding only.
- `.gitignore` essentials: Python (`__pycache__/`, `*.pyc`, `.venv/`, `dist/`, `build/`), tool caches (`.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.coverage`, `htmlcov/`), secrets (`.env`), ML artifacts (`data/`, `models/`, `checkpoints/`, `wandb/`, `runs/`, `*.ckpt`), OS noise (`Thumbs.db`, `Desktop.ini`), notebook checkpoints.
- Model weights and datasets stay OUT of git entirely — no Git LFS for now (artifact storage is a training-change decision).
- `.gitattributes` with `* text=auto eol=lf` — mandatory for the Windows↔WSL2 shared workflow (§7).
- `.git` inside OneDrive works acceptably: heavy directories are gitignored, so OneDrive only syncs source.

### 6. Dependency pinning strategy

| Tranche | Contents | Rationale |
| --- | --- | --- |
| **Now (this change)** | runtime: `jsonschema`; dev group: `pytest`, `pytest-cov`, `ruff`, `mypy` | Everything the first tests and quality gates need; pure-Python, platform-agnostic, installs identically on Windows and WSL2; small and fast |
| **Deferred (training change)** | `torch` (cu128+ build for Blackwell), `transformers`, `peft`, `trl`, `accelerate`, `datasets`, `bitsandbytes` | Heavy (~GBs), CUDA-version-sensitive, platform-sensitive (Windows vs Linux wheels differ). Pinning them now on native Windows would bake a wrong/misleading lock. Their index configuration (`[tool.uv.sources]` → PyTorch cu128 index) belongs to the change that actually needs them |

Recommendation: do NOT pre-declare the ML stack (not even as commented placeholders or unlocked extras). The training change's proposal will state exact versions plus GPU/VRAM and fallback per project rules.

### 7. WSL2 consideration

Facts: WSL2 with Ubuntu-24.04 is already installed; driver 610.74 supports CUDA inside WSL2; the RTX 5070 is usable via GPU paravirtualization.

**Recommendation: hybrid, by design.**

- **Scaffolding targets BOTH runtimes**: core tooling (pytest, ruff, mypy, schema validation) is pure Python and must run green on native Windows AND in WSL2. Nothing in the scaffold may be Windows-specific — `pathlib` everywhere, Python entry points instead of shell scripts.
- **Training targets WSL2**: bitsandbytes/QLoRA is best-supported on Linux; native-Windows bnb wheels exist but remain the second-class path. The training change will install the ML stack INSIDE Ubuntu-24.04 with cu128 wheels.
- **I/O topology**: OneDrive + `/mnt/c` is slow for thousands of small files and multi-GB checkpoints, and OneDrive file-locking fights long training runs. For training, clone the repo into the WSL home (`~/projects/fine_tuning_model`) and keep `data/`/`models/` on the WSL-native filesystem. Day-to-day editing can stay on Windows.
- `.gitattributes` (`eol=lf`) prevents CRLF breakage across the boundary.

## Recommendation

Adopt: **uv + uv-managed Python 3.12 + src-layout (`cloudops_fc`) + pytest/pytest-cov with an 80% floor + ruff + pragmatic mypy + git init with ML-aware .gitignore/.gitattributes + core-only dependencies (ML stack explicitly deferred) + an OS-agnostic scaffold with WSL2 as the designated training runtime.**

This minimizes what can go wrong now (small, pure-Python, cross-platform) while leaving zero rework for the training change (uv sources, .gitattributes, and layout are already correct).

## Risks

- **VRAM headroom**: 12 GB is the floor for QLoRA on an 8B model — feasible (NF4 + paged optimizers + gradient checkpointing + short sequences, which function-calling data naturally has) but with no headroom. Fallback per project rules: smaller base model (3B/1B) or cloud GPU. Must be stated in the training proposal.
- **Blackwell wheel mismatch**: RTX 5070 (sm_120) requires torch cu128+ builds; older cu121/cu118 wheels will silently not use the GPU. The training change must pin the right index.
- **OneDrive sync churn**: venvs/checkpoints under OneDrive cause sync storms and file-locking; mitigated by .gitignore + WSL-native training directories, but discipline is required.
- **Python 3.14 ecosystem edge cases**: torch declares 3.10–3.14 support, but compiled add-ons lag; pinning 3.12 sidesteps this entirely.
- **Scope creep**: pulling torch into this change would double its size and failure modes; the deferral boundary must hold.

## Ready for Proposal

**Yes.** Scope for `sdd-propose`: git init; uv-based `pyproject.toml` (core + dev deps only); uv-managed Python 3.12; src-layout skeleton with `schemas` package data; first schema-validation test suite; ruff + mypy config; `.gitignore` / `.gitattributes` / `.env.example` / `README.md`; and an update to `openspec/config.yaml` (test + coverage commands, coverage threshold 80, `strict_tdd: true`). Explicitly out of scope: torch, transformers, peft, trl, datasets, bitsandbytes, GPU validation, training code.
