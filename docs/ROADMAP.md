# Roadmap

ArcOps v1 proves the core loop: local model → validated tool call → safe
execution. The roadmap turns that loop into a product a team can adopt.

## Near (v1.1)

**Goal: make the local demo trustworthy for a design partner.**

- Publish a full evaluation report for the standard, template, unseen and
  challenge modes.
- Add automated TUI coverage (Textual pilot tests) and a LocalStack smoke test
  in CI.
- Add an approval and audit log: who requested what, which tool call, which
  policy decision, which result.
- Add S3 and Lambda tools behind the same schema/safety contract.
- Add cost guardrails: monthly budget per workspace and a hard confirmation
  above a threshold.
- Package a one-command LocalStack + TUI demo for macOS/Linux/Windows.

## Next (v1.2)

**Goal: make it useful for a team, not just a single operator.**

- Multi-step plans with an explicit dry-run/diff before execution.
- Policy engine (OPA or equivalent) for organization-specific rules.
- Terraform/Pulumi adapters: propose an action and show the IaC diff.
- Team workspaces, shared audit history and role-based approval.
- More AWS services (IAM read-only, CloudWatch, ECS) with the same validation
  contract.
- Evaluation dashboard and regression gates on every adapter release.

## Later

**Goal: turn the open-source engine into an open-core product.**

- Hosted control plane for teams that do not want to run the stack.
- SSO/RBAC and enterprise audit retention.
- Multi-cloud adapters (GCP/Azure) behind the same tool-call contract.
- Plugin SDK for custom tools and internal APIs.
- Distilled 1.5B adapter for CPU/laptop inference.
- Public benchmark of tool-call accuracy across models and prompts.

## Open-core hypothesis

The local engine stays Apache 2.0. The commercial surface is the team layer:

| Open source | Commercial |
|---|---|
| Local inference | Hosted control plane |
| Safety layer and schemas | Policy packs and approvals |
| CLI, TUI, API, MCP | SSO/RBAC, audit retention |
| Dataset/eval protocol | Team evaluation dashboards |
| Community tools | Enterprise support and integrations |

This is a hypothesis to test with design partners, not a shipped pricing page.

## Success metrics

- **Tool accuracy:** correct tool name on the challenge set.
- **Field accuracy:** correct arguments on unambiguous prompts.
- **Exact match:** fully correct tool calls without repair.
- **Safety precision:** hallucinated parameters blocked vs valid calls blocked.
- **Time to first action:** prompt → validated tool call → executed action.
- **Cost per action:** local inference cost + execution cost.
- **Adoption:** weekly active operators, tools per workspace, approved actions.

## Non-goals

- A general-purpose chatbot.
- Autonomous production changes without approval.
- Broad multi-cloud support in v1.
- Replacing Terraform or a full IaC platform.
- A hosted SaaS before the local workflow is validated with real teams.

## How to contribute to the roadmap

Open an issue with the workflow you want to automate, the tool call you would
expect, and the safety policy you would require. The best roadmap input is a
real CloudOps request that currently costs someone time.
