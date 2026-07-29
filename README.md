# ArcOps

**Natural language → AWS tool calls. 100% local. No data leaves your machine.**

<p align="center">
  <img src="https://img.shields.io/github/license/CodeSantiago/ArcOps" alt="License">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python">
  <img src="https://img.shields.io/badge/cuda-13.0-green" alt="CUDA">
  <img src="https://img.shields.io/badge/model-7B%20QLoRA-orange" alt="Model">
</p>

ArcOps is a fine-tuned language model (Qwen2.5-7B + QLoRA) that converts CloudOps instructions into structured JSON tool calls ready for AWS API execution. It runs entirely on your hardware — no OpenAI, no API costs, no data sent to third parties.

```
User: "Create a t3.micro server in us-east-1 with port 80 open"
  ↓  ArcOps fine-tuned model (local, private)
Tool call: {"arguments": {"instance_type": "t3.micro", "region": "us-east-1",
            "security_group_rules": [{"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"}]},
            "name": "create_ec2_instance"}
  ↓  Safety layer (cost estimate, policy check, schema validation)
  ↓  LocalStack (AWS simulator) or real AWS
Result: EC2 instance created (~$8/mo)
```

---

## Features

- **100% private** — runs on your GPU, no data leaves your machine
- **Deterministic** — same input always produces same output (greedy decoding)
- **No hallucinations** — schema validation blocks invented parameters
- **Cost-aware** — estimates monthly costs before executing
- **Safety layer** — blocks destructive actions, flags disruptive operations
- **Multi-tool** — EC2, RDS, Cost Explorer (extensible)
- **Bilingual** — works in English and Spanish
- **LocalStack integration** — test without spending real AWS money

## Quick Start

### Prerequisites

- NVIDIA GPU with 12GB+ VRAM (RTX 3070+, RTX 4070+, RTX 5070, etc.)
- WSL2 with Ubuntu 24.04 (Windows) or native Linux
- uv package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Docker (for LocalStack)

### Install & Run

```bash
# Clone
git clone https://github.com/CodeSantiago/ArcOps.git
cd ArcOps

# Setup
uv sync

# Download the fine-tuned adapter
huggingface-cli download CodeSantiago/arcops --local-dir checkpoints/final
```

```bash
# Quick prompt (auto-starts model server ~30s first time)
arcops "Create a t3.micro server in us-east-1 with port 80"

# Result:
# {"arguments": {"instance_type": "t3.micro", "region": "us-east-1", ...}, "name": "create_ec2_instance"}
```

### Docker (no GPU, slower)

```bash
docker pull codesantiago/arcops
docker run -p 8080:8080 -e ARC_OPS_ADAPTER=codesantiago/arcops codesantiago/arcops
# API: http://localhost:8080/predict -d '{"prompt":"Create a t3.micro server"}'
```

---

## Usage

### CLI

```bash
# Basic prompt
arcops "Create a t3.micro server in us-east-1 with port 80"

# With safety check (auto-enabled)
arcops "Restart the production database with failover"
# → Shows cost, flags disruption, requires approval

# JSON-only output (for scripts)
arcops --json "Create a server with tags Name=web, Env=prod"

# Execute against LocalStack
arcops exec "Create a t3.micro server"

# Open terminal dashboard
arcops tui
```

### TUI Dashboard

```bash
cd ~/ArcOps && uv run python app/tui.py
```

Interactive terminal UI with:
- Real-time resource list (EC2, RDS)
- Create (AI-powered), Stop, Start, Delete
- Tag management
- LocalStack health monitoring

### MCP Server (for opencode, Claude, Cursor)

```json
{
  "mcp": {
    "arcops": {
      "command": ["uv", "run", "python", "scripts/mcp_server.py"],
      "type": "local"
    }
  }
}
```

Then from any MCP client: `"Create a t3.micro server in us-east-1"`

### API

```bash
# Start API
docker run -p 8080:8080 codesantiago/arcops

# Predict
curl -s localhost:8080/predict \
  -d '{"prompt":"Create a t3.micro server in us-east-1"}' \
  -H "Content-Type: application/json"

# Predict with safety check
curl -s localhost:8080/predict/safe \
  -d '{"prompt":"Restart the production database"}' \
  -H "Content-Type: application/json"
```

---

## Supported Tools

| Tool | AWS API | Parameters |
|------|---------|------------|
| `create_ec2_instance` | EC2 RunInstances | region (required), instance_type (required), security_group_rules, tags, key_name, subnet_id, associate_public_ip |
| `restart_database` | RDS RebootDBInstance | db_instance_identifier (required), region (required), force_failover |
| `get_billing_alert` | Cost Explorer GetCostAndUsage | time_period_start, time_period_end, granularity (DAILY/MONTHLY), metrics, group_by_service |

---

## Safety Layer

Every tool call is automatically checked before execution:

| Check | What it does |
|-------|-------------|
| Schema validation | Rejects invented parameters (e.g. `log_event`) |
| Required fields | Blocks calls missing mandatory params |
| Cost estimation | Shows monthly cost estimate before creating resources |
| Disruptive action flag | Flags operations that cause downtime (e.g. DB restart) |
| Policy enforcement | Blocks destructive operations in production |

```
> Create a t3.micro server in us-east-1

-- Safety Check --
~$8/mo (t3.micro)

[ok] Created i-12345678
```

---

## Model Training

### Dataset

- **10,854 synthetic examples** across 3 tools
- Balanced field distributions (50/50 force_failover, 12% multi-metric, 15% multi-rule security groups)
- Noise examples to prevent hallucination ("but also log the event" → ignored)
- City-to-region mapping examples ("Sydney" → "ap-southeast-2")
- Reproducible: `uv run python scripts/generate_dataset_v3.py`

### Training

```bash
# Quick training (~3h, rank 16, 2 epochs)
uv run python scripts/training/train.py --config scripts/training/quick_config.yaml

# Full training (~8h, rank 32, 4 epochs)
bash scripts/training/run.sh
```

### Results

| Metric | Value | What it means |
|--------|-------|---------------|
| Tool-name accuracy | 100% | Always picks the right AWS tool (EC2 vs RDS vs billing) |
| Field accuracy | 100% | Every parameter correct (region, instance_type, force_failover, etc.) |
| Exact-match accuracy | 100% | Full JSON output matches expected exactly |

The model achieves perfect accuracy on the held-out test set (1,086 examples). Test examples are drawn from the same distribution as training — this is expected for a deterministic task with a consistent dataset.

**What matters more: generalization to unseen prompts.** The model handles:
- Instance types not in training (`c6i.4xlarge`, `r5.2xlarge`, `t3.nano`)
- Ports never seen (8888, 6006, 6379, 27017)
- City names mapped correctly ("Sydney" → `ap-southeast-2`)
- Multi-service billing queries ("EC2 and RDS costs")
- Noise phrases ignored ("but also log the event", "notify me when done")
- No hallucinated parameters (`log_event`, `send_email`, `environment`, etc. are all blocked)

The safety layer provides a final defense: any hallucinated parameter is rejected before execution.

**Training details:** 10,854 examples, 4 epochs, rank 32, LR 5e-5, ~8h on RTX 5070.

---

## Model Variants

| Model | Size | VRAM | Speed | Accuracy |
|-------|------|------|-------|----------|
| **7B (QLoRA)** | 15GB base + 323MB adapter | ~8.3GB | ~2s/inference | Best |
| **1.5B (QLoRA)** | 3GB base + 80MB adapter | ~3GB | ~0.5s/inference | Good, runs on CPU |

Both available on HuggingFace: [CodeSantiago/arcops](https://huggingface.co/CodeSantiago/arcops)

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Base model | Qwen2.5-7B-Instruct (Apache 2.0) |
| Fine-tuning | PEFT + TRL + QLoRA (4-bit) |
| Hardware | NVIDIA RTX 5070 12GB (Blackwell sm_120) |
| Quantization | bitsandbytes 0.50.0 |
| Backend | FastAPI (REST), Bottle (desktop UI) |
| Desktop UI | pywebview (native Windows window) |
| Terminal UI | Python curses / print-input |
| AWS simulation | LocalStack |
| Container | Docker |
| Model hosting | HuggingFace Hub |
| Package manager | uv |

---

## Project Structure

```
ArcOps/
├── app/
│   ├── api.py            # FastAPI REST server
│   ├── desktop.py        # Native Windows desktop app
│   ├── exec.py           # NL → execution runner
│   ├── safety.py         # Safety layer (validation, costs, policies)
│   ├── tui.py            # Terminal UI dashboard
│   └── index.html        # Web UI (optional)
├── scripts/
│   ├── training/
│   │   ├── train.py          # QLoRA training entrypoint
│   │   ├── eval.py           # Evaluation script
│   │   ├── pipeline_utils.py # Data formatting & metrics
│   │   ├── train_config.py   # Pydantic config model
│   │   ├── quick_config.yaml  # Quick training config (~3h)
│   │   ├── config_1.5b.yaml  # Small model training config
│   │   └── default_config.yaml # Production training config
│   ├── mcp_server.py         # MCP protocol server
│   ├── generate_dataset_v3.py # Dataset generator
│   ├── stress_test.py        # Integration test suite
│   ├── audit_dataset.py      # Dataset analysis tool
│   └── test_safety.py        # Safety layer tests
├── src/
│   └── cloudops_fc/schemas/  # Tool definitions (JSON Schema)
├── cloudops.py               # Main CLI entrypoint
├── PROJECT.md                # Detailed project documentation
├── JOURNEY.md                # Development journey & lessons learned
└── .env.example              # Environment configuration template
```

---

## Roadmap

- [x] 3 AWS tools (EC2, RDS, billing)
- [x] Safety layer with cost estimation
- [x] MCP server integration
- [x] Desktop UI (native Windows)
- [x] Terminal UI dashboard
- [x] Docker deployment
- [ ] Slack/Discord bot (approval workflows)
- [ ] Multi-turn conversations (chat history)
- [ ] Additional AWS services (S3, Lambda, IAM)
- [ ] Model quantization (GGUF) for pure CPU inference
- [ ] ONNX export for faster inference

---

## License

Apache 2.0

---

[Report a bug](https://github.com/CodeSantiago/ArcOps/issues) · [Contribute](https://github.com/CodeSantiago/ArcOps/pulls) · [HuggingFace model](https://huggingface.co/CodeSantiago/arcops)
