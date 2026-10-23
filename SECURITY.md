# Security Policy

ArcOps plans and executes cloud actions. Security is part of the product, not an
afterthought.

## Supported versions

| Version | Supported |
|---|---|
| `v1.0.x` | Yes |
| Older | No |

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting:

https://github.com/CodeSantiago/ArcOps/security/advisories/new

Do not open a public issue with exploit details, real AWS credentials, account
IDs or production resource names. Reports are handled on a best-effort basis.

## Safety defaults

- **LocalStack first.** Execution targets LocalStack unless real AWS is
  explicitly enabled.
- **Real AWS opt-in.** `ARC_OPS_REAL=1` and an interactive confirmation are both
  required.
- **Validated output.** Model output is parsed and checked against JSON Schema,
  known tool names and known EC2 types before execution.
- **No shell interpolation.** AWS execution uses argument lists, not shell
  strings.
- **Local API.** The FastAPI server binds to `127.0.0.1`; set
  `ARC_OPS_API_KEY` if you expose it.
- **Secrets stay out of git.** Use `.env` locally; it is gitignored.

## Scope

In scope:

- prompt injection that bypasses the tool/schema contract;
- model output that passes safety but should not execute;
- execution-path injection or privilege escalation;
- API authentication and localhost exposure issues;
- dependency and supply-chain risks.

Out of scope:

- the safety of a real AWS account configured by the user;
- LocalStack behavior;
- denial of service from intentionally huge prompts on a local machine;
- issues that require the attacker to already control the host.

## Prompt injection

The model is treated as untrusted. A prompt that convinces the model to emit an
unknown tool, an unknown parameter or a hallucinated instance type is blocked by
the safety layer. The model never receives direct AWS credentials and never
executes code itself.
