# CloudOps Agent — NL-to-JSON Tool Calling with Fine-Tuned Qwen2.5-7B

Fine-tune a small language model (7B) to convert natural language CloudOps instructions into structured JSON tool calls ready for AWS API execution. 100% local, no API costs, no data leaving your machine.

## The Problem

Cloud engineers spend hours writing CLI commands and API payloads for routine infrastructure tasks:

```
"Create a t3.medium server in us-east-1 with port 443 open"
```

A general-purpose LLM returns paragraphs of text. You still need to parse it, extract parameters, and format the API call. Errors mean broken infrastructure.

## The Solution

A fine-tuned Qwen2.5-7B-Instruct model that takes natural language and returns **only the structured JSON** — deterministic, schema-validated, ready to execute:

```json
{
  "name": "create_ec2_instance",
  "arguments": {
    "region": "us-east-1",
    "instance_type": "t3.medium",
    "security_group_rules": [{"port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0"}]
  }
}
```

## Architecture

```
User (NL) → MCP Server → Fine-tuned Qwen2.5-7B (QLoRA) → JSON → LocalStack/AWS
                ↑                                              |
                └─────────── runs on RTX 5070 12GB ─────────────┘
```

### Components

- **Base model**: Qwen/Qwen2.5-7B-Instruct (open weights, Apache 2.0)
- **Fine-tuning**: QLoRA (4-bit quantization) via PEFT + TRL SFTTrainer
- **Training**: RTX 5070 12GB (Blackwell), ~8.3GB VRAM usage
- **Dataset**: 8,000 synthetic NL→tool_call pairs (3 AWS tools)
- **MCP Server**: Connects to opencode, Claude Desktop, Cursor, etc.
- **Execution**: LocalStack (AWS mock, no real costs) or real AWS

### Supported Tools

| Tool | AWS API | Parameters |
|---|---|---|
| `create_ec2_instance` | EC2 RunInstances | region, instance_type, ami_id, security_group_rules, tags, etc. |
| `restart_database` | RDS RebootDBInstance | db_instance_identifier, region, force_failover |
| `get_billing_alert` | Cost Explorer GetCostAndUsage | time_period, granularity, metrics, group_by_service |

### Dataset Examples

| Natural Language | Tool Call |
|---|---|
| "Creame un server t3.micro en us-east-1 con puerto 80" | `{"name":"create_ec2_instance","arguments":{"region":"us-east-1","instance_type":"t3.micro","security_group_rules":...}}` |
| "Reiniciá la DB de producción que se colgó" | `{"name":"restart_database","arguments":{"db_instance_identifier":"prod-db-01","region":"us-east-1","force_failover":true}}` |
| "Cuánto gastamos este mes en AWS" | `{"name":"get_billing_alert","arguments":{}}` |

## Results

### Evaluation Metrics (260 test examples)

| Metric | Value |
|---|---|
| Tool-name accuracy | 99.87% |
| Field accuracy | 82.84% |
| Exact-match accuracy | 47.58% |

### Key Behaviors

- **100% valid JSON output** — never hallucinates parameters outside the schema
- **Deterministic** — same input always produces same output (greedy decoding)
- **No chatty text** — returns only the tool call, no explanations
- **Geographic mapping** — "Virginia" → us-east-1, "Oregon" → us-west-2
- **Size inference** — "chico" → t3.micro, "grande" → m5.large, "16GB" → c6i.2xlarge

### Interactive Demo

```
📝 > Cremá un server t3.medium en us-east-1 con el puerto 443 abierto
🤖 {"arguments": {"instance_type": "t3.medium", "region": "us-east-1", ...}, "name": "create_ec2_instance"}

📝 > Reiniciá la DB de producción
🤖 {"arguments": {"db_instance_identifier": "prod-db-01", "region": "us-east-1"}, "name": "restart_database"}

📝 > Cuánto gastamos este mes
🤖 {"arguments": {}, "name": "get_billing_alert"}
```

## Project Structure

```
cloudops-fc/
├── src/cloudops_fc/schemas/    # Tool definitions (JSON Schema)
│   ├── create_ec2_instance.json
│   ├── restart_database.json
│   ├── get_billing_alert.json
│   └── tool_definitions.json   # OpenAI function-calling format
├── data/
│   └── training_dataset.jsonl  # 8000 synthetic examples
├── scripts/
│   ├── generate_dataset.py     # Dataset generator (reproducible)
│   ├── training/
│   │   ├── smoke_test.py       # GPU/BNB environment validator
│   │   ├── train_config.py     # Pydantic config model
│   │   ├── train.py            # QLoRA SFTTrainer entrypoint
│   │   ├── eval.py             # Evaluation with 3 metrics
│   │   ├── pipeline_utils.py   # Tokenization & metric utils
│   │   ├── default_config.yaml # Hyperparameters
│   │   └── run.sh              # WSL2 launcher (rsync + train + eval)
│   ├── mcp_server.py           # MCP server for opencode/Claude integration
│   ├── test_model.py           # Interactive model test
│   └── test_prompts.py         # System prompt comparison
├── checkpoints/final/          # LoRA adapter weights
└── openspec/                   # Full SDD artifacts (specs, design, tasks)
```

## Quick Start

### Prerequisites

- NVIDIA GPU with 12GB+ VRAM (or cloud GPU)
- WSL2 with CUDA 12.8+ (Windows) or native Linux
- uv package manager

### Train

```bash
# Generate dataset (8,000 examples)
uv run python scripts/generate_dataset.py

# Full pipeline: smoke test → train → eval
bash scripts/training/run.sh
```

### Test

```bash
uv run python scripts/test_model.py
```

### MCP Integration

The project includes an MCP server that exposes the fine-tuned model as a tool for any MCP-compatible client (opencode, Claude Desktop, Cursor, VS Code).

### Tools Exposed

| Tool | Description |
|---|---|
| `cloudops_plan` | Convierte NL a JSON tool call (dry run, no ejecuta) |
| `cloudops_execute` | Convierte NL a JSON y lo ejecuta contra LocalStack |

### Configure in opencode.json

```json
{
  "mcp": {
    "cloudops-agent": {
      "command": [
        "wsl.exe", "~", "-d", "Ubuntu-24.04",
        "--cd", "/home/conta/fine_tuning_model",
        "uv", "run", "python", "scripts/mcp_server.py"
      ],
      "type": "local"
    }
  }
}
```

### Usage

From any MCP client:

```
User: "Creame un server t3.micro en us-east-1 con puerto 80"
Agent → cloudops_plan(prompt="Creame un server...")
       → {"tool_call": {"name": "create_ec2_instance", "arguments": {...}}}
```

Requires WSL2 with the fine-tuned model and uv installed.

Add to your `opencode.json`:

```json
{
  "mcp": {
    "cloudops-agent": {
      "command": ["uv", "run", "python", "scripts/mcp_server.py"],
      "type": "local"
    }
  }
}
```

Then in opencode: "Creame un server t3.micro en us-east-1"

## Tech Stack

| Technology | Purpose |
|---|---|
| Python 3.12 + uv | Runtime & package management |
| HuggingFace Transformers | Model loading & inference |
| PEFT + TRL | QLoRA fine-tuning |
| bitsandbytes | 4-bit quantization |
| HuggingFace Datasets | Data loading & splitting |
| Qwen2.5-7B-Instruct | Base model (open weights) |
| LocalStack | AWS mock (optional, for demo) |
| MCP Protocol | AI tool integration |
| pydantic | Configuration validation |

## What's Next

- [ ] Multi-turn conversations (chat history)
- [ ] HuggingFace Hub model upload
- [ ] Docker image for easy deployment
- [ ] Support for more AWS services
- [ ] Real user feedback dataset (beyond synthetic)
- [ ] ONNX export for faster inference

## License

Apache 2.0
