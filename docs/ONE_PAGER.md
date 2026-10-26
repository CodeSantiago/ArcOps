# ArcOps — Founder One-Pager

**Local-first natural language → validated AWS actions.**

ArcOps is a CloudOps agent that runs a fine-tuned 7B model on your own GPU,
turns plain English into structured AWS tool calls, validates them against a
deterministic safety layer, and executes against LocalStack by default. Real
AWS is an explicit opt-in.

This is a **v1 reference implementation** with an honest evaluation protocol,
not a hosted product yet.

---

## The problem

CloudOps work is full of small, repetitive translations:

- "Open port 80 on a t3.micro in us-east-1."
- "Restart the primary database with failover."
- "How much did we spend this month?"

Today that work becomes CLI commands, console clicks, API payloads, tickets and
runbooks. General-purpose LLMs can write the prose, but they are not reliable
execution engines: they hallucinate parameters, invent resources and cannot be
trusted with production credentials.

The gap is not "a smarter chatbot." The gap is **a trustworthy compiler from
intent to action**.

---

## The insight

Reliability comes from the **contract around the model**, not from a bigger
prompt.

1. **Narrow the domain.** Three high-frequency tools, one JSON Schema per tool,
   one engine.
2. **Make the model local.** A 7B model in 4-bit fits on a 12 GB consumer GPU;
   infrastructure context stays on the machine.
3. **Validate deterministically.** JSON Schema, known EC2 types, cost
   estimation, policy and approval gates surround the probabilistic model.
4. **Execute safely.** LocalStack is the default; real AWS requires a flag and
   an interactive confirmation.
5. **Measure honestly.** Deduplicate before splitting, hold out template
   families, enforce a consistency gate, and publish the protocol.

---

## The product

| Surface | What it does |
|---|---|
| CLI | `arcops "prompt"` → tool call + safety feedback |
| TUI | Textual dashboard: prompt, resources, create/stop/start/delete/tag |
| API | Localhost FastAPI with optional `X-API-Key` |
| MCP | `cloudops_plan` and `cloudops_execute` for agent clients |
| Executor | Plan by default; `--live` against LocalStack |

One engine (`cloudops_fc.core`) powers every surface. There is no duplicated
inference or AWS logic.

---

## Why now

- **Local models crossed the usefulness threshold for narrow structured
  tasks.** The remaining problem is systems engineering, not model size.
- **Cloud teams want automation without exporting context.** Prompts, resource
  names and account details can stay local.
- **Agent reliability is the bottleneck.** The market does not need another
  autonomous demo; it needs validated actions, auditability and safe defaults.

---

## Proof from v1

| Signal | Result |
|---|---|
| Dataset | 11,510 raw → 4,285 unique; 64 manual challenge prompts; 0 schema-invalid rows |
| Model | Qwen2.5-7B-Instruct + QLoRA adapter, 4-bit, single 12 GB GPU |
| Tests | 227 passed + 1 skipped without ML; 228 passed with GPU extras |
| Quality | `ruff` clean; `mypy --strict` clean |
| Coverage | 35% overall; ~58% of the engine; TUI manual |
| Quick eval | 5/5 tool selection, 6/11 fields, 2/5 exact on 5 built-in cases |
| End-to-end | EC2 create against LocalStack 3.0 on Windows + RTX 5070 |

The quick eval is deliberately labeled a smoke test. The full evaluation modes
(standard, template holdout, unseen values, 64-prompt challenge) are documented
in [EVALUATION.md](EVALUATION.md), including the policy that retired the old
inflated "100%" numbers.

---

## Differentiation

- **Tool-call compiler, not chatbot.** The output is a validated JSON action.
- **Deterministic safety around a probabilistic model.** Schema, known types,
  cost, policy and approval are separate from inference.
- **Local-first economics and privacy.** No per-token API bill for the model and
  no infrastructure context leaving the machine.
- **Evaluation discipline as a product feature.** The repo ships the dataset
  protocol, challenge set, split logic and consistency gate that most demos
  skip.
- **One engine, five surfaces.** CLI, TUI, API, MCP and executor stay in sync.

---

## Business model hypothesis (open-core)

The local engine stays Apache 2.0. The commercial surface is the team layer:

- centralized audit log and approval workflows;
- policy packs and cost guardrails;
- shared workspaces, SSO/RBAC and evaluation dashboards;
- a hosted control plane for teams that do not want to run the stack.

This is a hypothesis, not a shipped product. The open-source engine is the
distribution wedge and the proof of technical credibility.

---

## Initial wedge

**Design partners:** platform engineering, DevOps and CloudOps teams running
AWS, especially teams that already use LocalStack or Terraform and care about
keeping infrastructure context private.

**First paid jobs:**

1. Guardrailed self-service actions for routine requests.
2. Approval and audit trails for disruptive operations.
3. Cost-aware planning before resources are created.

**Go-to-market experiments:** open-source demos, a public benchmark/report on
tool-call accuracy, design-partner pilots, and content around "validated agents
for infrastructure."

---

## Roadmap

**Near (v1.1)** — full eval report, TUI coverage, approval/audit log, S3 and
Lambda tools, cost guardrails.

**Next (v1.2)** — multi-step plans, dry-run diff, policy engine (OPA),
Terraform/Pulumi adapters, team workspaces.

**Later** — hosted control plane, SSO/RBAC, multi-cloud, plugin SDK, distilled
1.5B adapter.

Full detail: [ROADMAP.md](ROADMAP.md).

---

## What we are looking for

- Design partners with real CloudOps workflows.
- Feedback on the safety and approval model.
- Pilots for the team/audit layer.
- Introductions to platform-engineering and CloudOps leaders.

---

## Non-goals for v1

- A general-purpose chatbot.
- Autonomous production changes without approval.
- Broad multi-cloud support.
- A hosted SaaS control plane.
- A claim of production readiness.

ArcOps v1 is a strong engineering foundation and a clear product thesis. The
next step is to validate the workflow with real teams, not to add more tools for
the sake of a demo.
