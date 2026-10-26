# Architecture

ArcOps is one engine with five thin interfaces. The design goal is to make the
probabilistic part (model inference) as small and isolated as possible, and the
deterministic parts (validation, policy, execution) explicit and testable.

## Goals

- Convert natural-language CloudOps requests into structured AWS tool calls.
- Run inference locally, without a hosted model API.
- Validate every call before anything executes.
- Execute against LocalStack by default; real AWS only with explicit opt-in.
- Keep CLI, TUI, API, MCP and the executor on the same code path.
- Make the evaluation protocol reproducible and honest.

## Non-goals

- General-purpose chat.
- Autonomous production changes without approval.
- Broad multi-cloud coverage.
- A hosted control plane (roadmap).
- Replacing Terraform or a full IaC platform.

## System map

```text
┌──────────────────────────────────────────────────────────────┐
│ Interfaces                                                   │
│  CLI: cloudops_fc.cli        → arcops                        │
│  TUI: cloudops_fc.tui        → Textual dashboard             │
│  API: app.api                → FastAPI on 127.0.0.1:8080     │
│  MCP: scripts/mcp_server.py  → cloudops_plan / execute       │
│  Exec: app.exec              → plan / --live LocalStack      │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
                 cloudops_fc.core
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   infer()             safety.check()      execute()
   Qwen2.5-7B           JSON Schema         AWS CLI
   + LoRA, 4-bit        known EC2 types     LocalStack (default)
   greedy decoding      cost + policy       real AWS (opt-in)
```

## Module responsibilities

| Module | Responsibility |
|---|---|
| `cloudops_fc.core` | Inference, safety call, execution, resource actions |
| `cloudops_fc.safety` | JSON Schema validation, known EC2 types, cost, policy |
| `cloudops_fc.models` | Model selection (`7b` / `1.5b`), adapter resolution |
| `cloudops_fc.cli` | `arcops` entry point, `--json`, `--eval`, `tui` |
| `cloudops_fc.tui` | Textual dashboard; same engine, inline confirmation |
| `cloudops_fc.schemas` | Packaged JSON Schemas and validation helpers |
| `app.api` | FastAPI wrapper, API key, `/predict`, OpenAI-compatible endpoint |
| `app.exec` | Plan/execute demo for LocalStack and real AWS |
| `scripts/mcp_server.py` | MCP stdio server exposing plan/execute |
| `scripts/training/*` | Dataset splits, training, evaluation, configs |

`app/tui.py` and `app/safety.py` are compatibility shims that re-export the
canonical modules. They exist so old imports keep working.

## Request flow

1. **Input.** A prompt arrives from the CLI, TUI, API or MCP.
2. **Inference.** `core.infer()` loads the configured model once, renders the
   system prompt plus user message, and generates a short JSON tool call.
3. **Parse.** The response is parsed into `{name, arguments}`. No prose is
   accepted as an action.
4. **Safety.** `safety.check()` validates the tool, parameters, JSON Schema,
   known EC2 types, cost and policy. The result includes `blocked`,
   `requires_approval`, warnings and an estimated monthly cost.
5. **Approval.** Disruptive actions require an explicit confirmation callback.
   Without one, the action is refused.
6. **Execution.** `core.execute_tool_call()` builds an AWS CLI command and runs
   it against LocalStack or real AWS.
7. **Feedback.** The interface reports the result, cost and any warnings.

## Inference

- Base model: `Qwen/Qwen2.5-7B-Instruct` (Apache 2.0).
- Adapter: `CodeSantiago/arcops` (public LoRA adapter).
- Quantization: 4-bit bitsandbytes.
- Decoding: greedy (`do_sample=False`), short output (`MAX_NEW_TOKENS=256`).
- System prompt: "You are a CloudOps infrastructure assistant. Output ONLY the
  JSON tool call. No explanations, no markdown."
- Device: CUDA when available; CPU fallback is possible but slow.
- Runtime is imported lazily, so the base package works without PyTorch.

The model is a **compiler front-end**, not an agent. It does not choose tools
autonomously, call AWS directly, or execute code.

## Safety

The safety layer is deterministic and has no ML dependency. It is used by every
interface.

| Layer | What it enforces |
|---|---|
| Tool registry | Only the three known tools |
| Allowed keys | Unknown parameters are blocked |
| Required keys | Missing mandatory parameters are blocked |
| JSON Schema | Types, patterns, enums, extra keys |
| Known EC2 types | Only instance types in the priced/safety set |
| Cost | Approximate monthly EC2 cost |
| Policy | Destructive tools (when registered) blocked in `production` |
| Approval | Disruptive tools require a confirmation callback |

A safety result is not a boolean. It carries warnings, errors, cost, `blocked`
and `requires_approval`, so each interface can render the right decision.

## Execution

- **Default target:** LocalStack at `http://localhost:4566`.
- **Real AWS:** requires `ARC_OPS_REAL=1` and an interactive confirmation.
- **EC2:** creates the requested security group and ingress rules before
  `run-instances`; uses `ARC_OPS_DEFAULT_AMI` (`ami-12345678`) for LocalStack
  when the model omits `ami_id`; requires an explicit AMI for real AWS.
- **Count:** the AWS CLI exposes a single instance count; `min_count` maps to
  `--count`.
- **RDS:** `reboot-db-instance`, with `--force-failover` when requested.
  LocalStack community does not implement RDS.
- **Billing:** read-only; Cost Explorer is unavailable in LocalStack.
- **Resources:** `get_all`, `act`, `tag_it` and `create` are the shared resource
  actions used by the TUI.

The executor uses argument lists with `subprocess`, not shell interpolation.

## Interfaces

All interfaces are thin. They differ in presentation and approval UX, not in
business logic.

- **CLI:** plan + safety by default; `--json` for machines; `--eval` for a quick
  accuracy check; `tui` to launch the dashboard.
- **TUI:** Textual dashboard, responsive three-column layout, inline prompt and
  inline `y/n` confirmation.
- **API:** FastAPI, localhost-bound, optional `X-API-Key`, `/predict` and an
  OpenAI-compatible `/v1/chat/completions` shim.
- **MCP:** stdio server with `cloudops_plan` and `cloudops_execute`; execution is
  LocalStack-only because MCP has no interactive approval channel.
- **Exec:** repo-only demo; plan by default, `--live` for LocalStack, `--real`
  for real AWS behind both an environment flag and a confirmation.

## Extension points

### Add a tool

1. Add a JSON Schema in `src/cloudops_fc/schemas/`.
2. Add the tool to `TOOL_SCHEMAS` in `safety.py` and to the schema registry tests.
3. Extend `core._execute_tool_call()` and `describe_actions()`.
4. Add a builder test and a safety test.
5. Update the README tool table and the dataset generator if the model should
   learn it.

### Add a model

1. Extend `cloudops_fc.models.resolve_model_config()`.
2. Add a config file under `scripts/training/`.
3. Keep the adapter configurable via `ARC_OPS_ADAPTER`.
4. Re-run the evaluation modes and report the mode next to the score.

### Add an interface

Keep it thin: call `core.infer()`, `safety.check()` and
`core.execute_tool_call()`; do not duplicate safety or AWS logic. Add a test
that mocks the engine.

## Testing strategy

- **Unit tests** cover schemas, safety, command builders, model resolution,
  dataset splits, evaluation metrics and MCP protocol behavior.
- **No ML stack required** for the default suite; torch/transformers are lazy.
- **GPU paths** are exercised manually and with `scripts/training/smoke_test.py`.
- **TUI** is manually/integration tested against LocalStack; it currently has
  0% automated coverage.
- **CI** runs lint, mypy, imports, `app.exec --help`, packaged-schema checks, the
  full non-GPU suite and a wheel smoke test on Python 3.12/3.13.

## Failure modes

| Failure | Behavior |
|---|---|
| Model returns invalid JSON | Parse error; no action executes |
| Model invents a parameter | Safety blocks the call |
| Model invents an instance type | Safety blocks the call |
| Missing required field | Safety blocks the call |
| LocalStack is down | Execution returns an error |
| RDS on LocalStack community | AWS returns an internal failure; documented limitation |
| Real AWS without opt-in | Execution refuses |
| Approval missing | Safety refuses the action |

## Design decisions

- **One engine, many faces.** Prevents drift between CLI, TUI, API and MCP.
- **JSON Schema at runtime.** The same schemas used by tests are enforced before
  execution.
- **Known-type allowlist.** A broad regex accepts real AWS families such as
  `c6i`/`t4g`; a priced allowlist blocks hallucinated types.
- **LocalStack first.** Demos and tests never touch real infrastructure.
- **No checkpoint in the repo.** The public adapter is the source of truth; the
  evaluation protocol is the reproducibility contract.
- **Honest results.** The README and evaluation docs explicitly retire the old
  leaked-split numbers.
