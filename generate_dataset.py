#!/usr/bin/env python3
"""Generate a synthetic fine-tuning dataset for CloudOps function calling.

Reads tool definitions from src/cloudops_fc/schemas/tool_definitions.json
and outputs ~2650 examples in JSONL format to data/training_dataset.jsonl.
"""

import json
import os
import random
import re
from datetime import date, timedelta

SEED = 42
TODAY = date(2026, 7, 24)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
TOOL_DEFS_PATH = os.path.join(
    PROJECT_ROOT, "src", "cloudops_fc", "schemas", "tool_definitions.json"
)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "training_dataset.jsonl")

# ---------------------------------------------------------------------------
# Constants from the tool definitions
# ---------------------------------------------------------------------------

REGIONS = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "eu-west-1", "eu-central-1", "eu-west-2",
    "ap-southeast-1", "ap-southeast-2", "ap-northeast-1",
    "sa-east-1", "ca-central-1",
]

REGION_TO_NAME = {
    "us-east-1": "Virginia",
    "us-east-2": "Ohio",
    "us-west-1": "California",
    "us-west-2": "Oregon",
    "eu-west-1": "Irlanda",
    "eu-central-1": "Frankfurt",
    "eu-west-2": "Londres",
    "ap-southeast-1": "Singapur",
    "ap-southeast-2": "Sídney",
    "ap-northeast-1": "Tokio",
    "sa-east-1": "São Paulo",
    "ca-central-1": "Canadá",
}

INSTANCE_TYPES = [
    "t3.micro", "t3.medium", "m5.large", "m5.xlarge",
    "c6i.large", "c6i.2xlarge", "r5.large", "t2.micro",
]

DB_INSTANCE_IDS = [
    "prod-db-01", "staging-mysql", "analytics-postgres", "app-db-primary",
    "users-db", "logs-db", "inventory-db", "payments-db", "cms-db",
    "backup-db", "reporting-db", "audit-db", "ecommerce-db", "auth-db",
    "ml-db", "search-db",
]

KEY_NAMES = [
    "mi-key", "prod-key", "dev-key", "default-key",
    "ops-key", "admin-key", "bastion-key", "vpn-key", "ci-key", "ro-key",
    "deploy-key", "monitoring-key", "backup-key",
]

SUBNET_IDS = [
    "subnet-abc123", "subnet-def456", "subnet-789ghi",
    "subnet-0a1b2c3d", "subnet-4e5f6g7h",
    "subnet-1234abcd", "subnet-5678efgh", "subnet-9abc0def",
]

CIDRS = [
    "0.0.0.0/0", "10.0.0.0/16", "192.168.1.0/24",
    "172.16.0.0/12", "10.10.0.0/16", "10.20.0.0/16",
    "10.30.0.0/16",
]
PROTOCOLS = ["tcp", "udp", "icmp"]

BILLING_METRICS = [
    "BlendedCost", "UnblendedCost", "UsageQuantity",
    "AmortizedCost", "NetUnblendedCost",
]

AMI_IDS = [
    "ami-0abcdef1234567890", "ami-12345678", "ami-0a1b2c3d",
    "ami-0e1f2a3b4c5d6e7f8", "ami-0deadbeef",
    "ami-0c55b159cbfafe1f0", "ami-0abcdef1234567890",
]

PROJECT_NAMES = [
    "migration", "platform-upgrade", "cost-optimization",
    "new-feature", "scaling", "security-audit",
    "data-lake", "microservices", "monitoring",
]

# Maps natural size words to instance types for variety in NL
SIZE_DESC_MAP = {
    "chica": ["t3.micro", "t2.micro", "t3.medium"],
    "mediana": ["t3.medium", "m5.large"],
    "grande": ["m5.xlarge", "c6i.2xlarge"],
    "poderosa": ["c6i.2xlarge", "r5.large"],
    "potente": ["c6i.2xlarge"],
    "económica": ["t3.micro", "t2.micro"],
    "económico": ["t3.micro", "t2.micro"],
    "liviana": ["t3.micro"],
    "pesada": ["c6i.2xlarge", "r5.large"],
}

SERVICES = ["EC2", "RDS", "S3", "Lambda", "ECS", "ELB", "CloudFront", "DynamoDB", "SNS", "SQS"]

SYSTEM_PROMPT = (
    "Eres un asistente de infraestructura cloud. "
    "Debes responder ÚNICAMENTE con tool calls en formato JSON."
)

MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detail_str(parts):
    """Join a list of detail phrases with 'con ' prefix if non-empty."""
    if not parts:
        return ""
    return " con " + ", ".join(parts)


def _random_date(start, end):
    """Return a random date between start and end (inclusive)."""
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def _make_sg_rules(count=None):
    """Generate 1-4 security group rules."""
    port_options = [22, 80, 443, 3389, 5432, 3306, 27017, 8080, 8443, 9090, 3000, 5000, 6379, 9200]
    n = count if count else random.randint(1, 4)
    selected = random.sample(port_options, min(n, len(port_options)))
    rules = []
    for port in selected:
        proto = "tcp"
        if port == 0:
            proto = "icmp"
        rules.append({
            "port": port,
            "protocol": proto,
            "cidr": random.choice(CIDRS),
        })
    return rules


def _make_tags(count=None):
    """Generate 1-4 tags."""
    pool = [
        ("Name", "web-server"), ("Name", "api-server"), ("Name", "db-server"),
        ("Name", "cache-server"), ("Name", "worker"), ("Name", "load-balancer"),
        ("Name", "bastion"), ("Name", "monitoring"), ("Name", "batch-processor"),
        ("Name", "queue-consumer"),
        ("Environment", "prod"), ("Environment", "staging"),
        ("Environment", "dev"), ("Environment", "qa"), ("Environment", "testing"),
        ("Project", "migration"), ("Project", "platform-upgrade"),
        ("Project", "cost-optimization"), ("Project", "new-feature"),
        ("Project", "scaling"), ("Project", "security-audit"),
        ("Owner", "devops"), ("Owner", "platform"), ("Owner", "sre"),
        ("Owner", "infra"), ("Owner", "backend"),
        ("CostCenter", "cc-123"), ("CostCenter", "cc-456"),
        ("CostCenter", "cc-789"), ("CostCenter", "cc-101"),
        ("Team", "platform"), ("Team", "infra"), ("Team", "backend"),
        ("Team", "frontend"), ("Team", "data"), ("Team", "ml"),
        ("ManagedBy", "terraform"), ("ManagedBy", "cloudformation"),
        ("ManagedBy", "pulumi"),
        ("Tier", "frontend"), ("Tier", "backend"), ("Tier", "data"),
        ("Tier", "cache"),
    ]
    n = count if count else random.randint(1, 4)
    chosen = random.sample(pool, min(n, len(pool)))
    return [{"key": k, "value": v} for k, v in chosen]


def _make_record(user_msg, tool_name, args):
    """Build a single JSONL record."""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(args, ensure_ascii=False),
                        },
                    }
                ],
            },
        ]
    }


# ---------------------------------------------------------------------------
# create_ec2_instance generators
# ---------------------------------------------------------------------------

_EC2_TEMPLATES = [
    # === Casual / imperative ===
    "Creame un servidor {instance_type} en {region}{details}",
    "Levantame una instancia EC2 {instance_type} en {region_name}{details}",
    "Dame un {instance_type} en {region}{details}",
    "Dale, levantame un {instance_type} en {region_name}{details}",
    "Che, dale, levantame un {instance_type} en {region_name}{details}",
    "Dale, poneme un {instance_type} en {region_name}{details}",
    "Che, armame un server {instance_type} en {region}{details}",
    "Levantame un server {instance_type} en {region}, urgente{details}",
    "Server en {region}, {instance_type}, ya{details}",
    "Dale, {instance_type} en {region_name} ya mismo{details}",
    # === "Che" / Rioplatense informal ===
    "Che, necesito un {instance_type} en {region_name}{details}",
    "Che, necesito que me levantes un {instance_type} en {region_name}{details}",
    "Che, levantame un {instance_type} en {region_name}, dale?{details}",
    "Che, para el proyecto {project} necesito un server en {region_name}{details}",
    # === Neutral declarative ===
    "Necesito un server en {region_name}, {specs}",
    "Podés levantarme un server {instance_type} en {region}{details}",
    "Podrías crear una instancia {instance_type} en {region}{details}?",
    "Necesito un server en {region_name}, específicamente un {instance_type}{details}",
    "Instancia EC2 en {region}, tipo {instance_type}{details}",
    "Quiero un {instance_type} en {region_name} para el proyecto nuevo{details}",
    "Creame {count} instancias {instance_type} en {region}{details}",
    "Dame {count} servers {instance_type} en {region_name}{details}",
    "Estamos migrando, necesito un {instance_type} en {region} ya{details}",
    "Che, cuánto sale un {instance_type} en {region_name}{details}?",
    # === Very formal ===
    "Solicito la creación de una instancia EC2 tipo {instance_type} en la región {region}{details}",
    "Sírvase aprovisionar una instancia EC2 de tipo {instance_type} en la región {region_name}{details}",
    "Solicito el aprovisionamiento de una instancia de cómputo tipo {instance_type} en {region_name}{details}",
    "Por favor, solicito la creación de {count} instancia(s) EC2 tipo {instance_type} en la región {region}{details}",
    "Solicito el aprovisionamiento de una instancia EC2 tipo {instance_type} en la región {region_name} con los siguientes parámetros{details}",
    # === Spanglish / English-mixed ===
    "Dame un server en {region_name}{details}",
    "Request: EC2 instance {instance_type} in {region}{details}",
    "I need a {instance_type} server in {region_name}{details}",
    "Necesito un {instance_type} in {region_name}{details}",
    "Please create an EC2 instance {instance_type} in {region}{details}",
    "Hey, can I get a {instance_type} in {region_name}{details}?",
    # === Size-inferred ===
    "Necesito una instancia en {region_name} que sea {size_description}{details}",
    "Dame un server {size_description} en {region_name}{details}",
    "Levantame algo {size_description} en {region}{details}",
    # === Context-rich ===
    "Estamos escalando, necesito {count} servers {instance_type} en {region}{details}",
    "Para la migración, levantame un {instance_type} en {region_name}{details}",
    "Preciso un server en {region_name} para el proyecto {project}{details}",
    "Necesito escalar horizontalmente, dame {count} {instance_type} en {region}{details}",
    # === Questions ===
    "Podés crearme un {instance_type} en {region_name}{details}?",
    "Me ayudás a levantar un server {instance_type} en {region}{details}?",
    "Se puede crear un {instance_type} en {region}{details}?",
]


def _gen_ec2():
    """Generate one create_ec2_instance example (normal)."""
    region = random.choice(REGIONS)
    instance_type = random.choice(INSTANCE_TYPES)
    args = {"region": region, "instance_type": instance_type}
    parts = []

    # ~88% get optional params
    if random.random() < 0.88:
        if random.random() < 0.35:
            args["key_name"] = random.choice(KEY_NAMES)
            parts.append(f"la key {args['key_name']}")

        if random.random() < 0.40:
            rules = _make_sg_rules()
            args["security_group_rules"] = rules
            ports = ", ".join(str(r["port"]) for r in rules)
            parts.append(f"puertos {ports} abiertos")

        if random.random() < 0.35:
            tags = _make_tags()
            args["tags"] = tags
            tag_str = ", ".join(f"{t['key']}={t['value']}" for t in tags)
            parts.append(f"tags: {tag_str}")

        if random.random() < 0.25:
            args["subnet_id"] = random.choice(SUBNET_IDS)
            parts.append(f"subnet {args['subnet_id']}")

        if random.random() < 0.35:
            args["associate_public_ip"] = random.choice([True, False])
            if args["associate_public_ip"]:
                parts.append("IP pública")

        # New: ami_id ~12%
        if random.random() < 0.12:
            args["ami_id"] = random.choice(AMI_IDS)

        # New: min_count / max_count ~10%
        if random.random() < 0.10:
            count = random.randint(2, 5)
            args["min_count"] = count
            args["max_count"] = count

    count_val = args.get("min_count", 1)
    details = _detail_str(parts)
    region_name = REGION_TO_NAME[region]
    specs = f"uno {instance_type}{details}" if parts else f"uno {instance_type}"

    # Map instance type to size description
    if instance_type in ("t3.micro", "t2.micro"):
        size_desc = random.choice(["chica", "económica", "liviana"])
    elif instance_type == "t3.medium":
        size_desc = random.choice(["mediana", "chica"])
    elif instance_type == "m5.large":
        size_desc = random.choice(["mediana", "grande"])
    elif instance_type in ("m5.xlarge",):
        size_desc = random.choice(["grande", "mediana"])
    elif instance_type in ("c6i.2xlarge", "r5.large"):
        size_desc = random.choice(["poderosa", "potente", "grande", "pesada"])
    else:
        size_desc = random.choice(["mediana", "grande"])

    project = random.choice(PROJECT_NAMES)

    template = random.choice(_EC2_TEMPLATES)
    user_msg = template.format(
        instance_type=instance_type, region=region,
        region_name=region_name, details=details, specs=specs,
        count=count_val, size_description=size_desc, project=project,
    )
    # Clean double spaces
    user_msg = user_msg.replace("  ", " ").strip()
    # Clean awkward comma+con patterns
    user_msg = user_msg.replace(", con", ",").replace("  ", " ").strip()
    return user_msg, args, "create_ec2_instance"


def _gen_ec2_all_params():
    """Generate an EC2 example with almost every optional parameter filled."""
    region = random.choice(REGIONS)
    instance_type = random.choice(INSTANCE_TYPES)
    count = random.randint(2, 4)
    rules = _make_sg_rules(3)
    tags = _make_tags(3)
    args = {
        "region": region,
        "instance_type": instance_type,
        "key_name": random.choice(KEY_NAMES),
        "security_group_rules": rules,
        "tags": tags,
        "subnet_id": random.choice(SUBNET_IDS),
        "associate_public_ip": True,
        "ami_id": random.choice(AMI_IDS),
        "min_count": count,
        "max_count": count,
    }
    ports = ", ".join(str(r["port"]) for r in rules)
    tag_str = ", ".join(f"{t['key']}={t['value']}" for t in tags)
    region_name = REGION_TO_NAME[region]

    templates = [
        "Necesito {count} instancias {instance_type} en {region_name} con todo: key {key_name}, "
        "puertos {ports} abiertos, subnet {subnet}, con IP pública, "
        "AMI {ami_id} y tags {tags}",
        "Solicito el aprovisionamiento de {count} instancias EC2 tipo {instance_type} en la región "
        "{region_name} con la clave {key_name}, reglas de seguridad para los puertos {ports}, "
        "subnet {subnet}, IP pública asignada, AMI {ami_id}, y las etiquetas {tags}",
        "Dame {count} servers {instance_type} en {region_name}, con {key_name}, "
        "puertos {ports}, subnet {subnet}, IP pública, AMI {ami_id}, "
        "y los tags {tags}",
    ]
    template = random.choice(templates)
    user_msg = template.format(
        count=count, instance_type=instance_type, region_name=region_name,
        key_name=args["key_name"], ports=ports, subnet=args["subnet_id"],
        ami_id=args["ami_id"], tags=tag_str,
    )
    return user_msg, args, "create_ec2_instance"


def _gen_ec2_minimal():
    """Generate an EC2 example with ONLY required params (minimal)."""
    region = random.choice(REGIONS)
    instance_type = random.choice(INSTANCE_TYPES)
    args = {"region": region, "instance_type": instance_type}
    region_name = REGION_TO_NAME[region]

    templates = [
        "Dame un {instance_type} en {region}",
        "Server {instance_type} en {region_name}",
        "{instance_type} en {region}, nada mas",
        "Creame un {instance_type} en {region_name} asi nomas",
        "Instancia {instance_type} en {region_name}",
        "Un {instance_type} en {region_name}",
        "Necesito un server en {region_name}, {instance_type}",
        "Levantame un {instance_type} en {region}, basico",
    ]
    template = random.choice(templates)
    user_msg = template.format(
        instance_type=instance_type, region=region, region_name=region_name,
    )
    return user_msg, args, "create_ec2_instance"


# Hand-crafted edge cases for create_ec2_instance
_EC2_EDGE = [
    # --- Original 20 (preserved) ---
    (
        "Necesito un server en Virginia con la key prod-key, puertos 22 y 443 abiertos, "
        "tags: Name=web-server Environment=prod, subnet subnet-abc123, con IP pública",
        {
            "region": "us-east-1", "instance_type": "m5.large",
            "key_name": "prod-key",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
            "tags": [
                {"key": "Name", "value": "web-server"},
                {"key": "Environment", "value": "prod"},
            ],
            "subnet_id": "subnet-abc123",
            "associate_public_ip": True,
        },
    ),
    (
        "Solicito el aprovisionamiento de una instancia EC2 tipo c6i.2xlarge "
        "en la región us-west-2 con la clave bastion-key, "
        "reglas de seguridad para los puertos 22/TCP y 8080/TCP desde 10.0.0.0/16, "
        "y las etiquetas Name=api-server y Environment=staging",
        {
            "region": "us-west-2", "instance_type": "c6i.2xlarge",
            "key_name": "bastion-key",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "10.0.0.0/16"},
                {"port": 8080, "protocol": "tcp", "cidr": "10.0.0.0/16"},
            ],
            "tags": [
                {"key": "Name", "value": "api-server"},
                {"key": "Environment", "value": "staging"},
            ],
        },
    ),
    (
        "Dale, levantame un t3.micro en sa-east-1, con la key default-key "
        "y los puertos 22, 80 y 443 abiertos para todo el mundo",
        {
            "region": "sa-east-1", "instance_type": "t3.micro",
            "key_name": "default-key",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
        },
    ),
    (
        "Necesito una instancia en Oregon, que sea chica, sin IP pública "
        "y con la subnet subnet-def456",
        {
            "region": "us-west-2", "instance_type": "t3.micro",
            "subnet_id": "subnet-def456",
            "associate_public_ip": False,
        },
    ),
    (
        "Che, para el proyecto migration necesito un r5.large en Frankfurt "
        "con las tags Project=migration y Team=platform, y puerto 5432 abierto "
        "para la red interna",
        {
            "region": "eu-central-1", "instance_type": "r5.large",
            "security_group_rules": [
                {"port": 5432, "protocol": "tcp", "cidr": "10.0.0.0/16"},
            ],
            "tags": [
                {"key": "Project", "value": "migration"},
                {"key": "Team", "value": "platform"},
            ],
        },
    ),
    (
        "Solicito una instancia EC2 en ap-northeast-1 tipo c6i.large "
        "con IP pública y la key admin-key",
        {
            "region": "ap-northeast-1", "instance_type": "c6i.large",
            "key_name": "admin-key",
            "associate_public_ip": True,
        },
    ),
    (
        "Dame un m5.xlarge en Londres con los puertos 22 y 3306 abiertos "
        "y las tags Name=db-server, Environment=prod, CostCenter=cc-456",
        {
            "region": "eu-west-2", "instance_type": "m5.xlarge",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 3306, "protocol": "tcp", "cidr": "10.0.0.0/16"},
            ],
            "tags": [
                {"key": "Name", "value": "db-server"},
                {"key": "Environment", "value": "prod"},
                {"key": "CostCenter", "value": "cc-456"},
            ],
        },
    ),
    (
        "Creame un server t2.micro en ca-central-1 nomas, sin nada raro",
        {"region": "ca-central-1", "instance_type": "t2.micro"},
    ),
    (
        "Levantame una instancia en Ohio, un m5.large, con la key ops-key "
        "y que tenga IP pública",
        {
            "region": "us-east-2", "instance_type": "m5.large",
            "key_name": "ops-key",
            "associate_public_ip": True,
        },
    ),
    (
        "Podés levantarme un c6i.2xlarge en Singapur con las tags "
        "Name=worker y ManagedBy=terraform, y el puerto 8443 abierto",
        {
            "region": "ap-southeast-1", "instance_type": "c6i.2xlarge",
            "security_group_rules": [
                {"port": 8443, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
            "tags": [
                {"key": "Name", "value": "worker"},
                {"key": "ManagedBy", "value": "terraform"},
            ],
        },
    ),
    (
        "Necesito un server en São Paulo con la subnet subnet-0a1b2c3d, "
        "los puertos 22 y 5432 abiertos, y las tags Environment=qa, Owner=sre",
        {
            "region": "sa-east-1", "instance_type": "t3.medium",
            "subnet_id": "subnet-0a1b2c3d",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "10.10.0.0/16"},
                {"port": 5432, "protocol": "tcp", "cidr": "10.10.0.0/16"},
            ],
            "tags": [
                {"key": "Environment", "value": "qa"},
                {"key": "Owner", "value": "sre"},
            ],
        },
    ),
    (
        "Dame un t3.medium en Irlanda con la key dev-key, puerto 27017 abierto, "
        "tags: Name=cache-server, y que NO tenga IP pública",
        {
            "region": "eu-west-1", "instance_type": "t3.medium",
            "key_name": "dev-key",
            "security_group_rules": [
                {"port": 27017, "protocol": "tcp", "cidr": "10.0.0.0/16"},
            ],
            "tags": [{"key": "Name", "value": "cache-server"}],
            "associate_public_ip": False,
        },
    ),
    (
        "Che, necesito una instancia en Tokio urgente, un c6i.large, "
        "con IP pública y las tags Project=cost-optimization, Team=infra",
        {
            "region": "ap-northeast-1", "instance_type": "c6i.large",
            "associate_public_ip": True,
            "tags": [
                {"key": "Project", "value": "cost-optimization"},
                {"key": "Team", "value": "infra"},
            ],
        },
    ),
    (
        "Solicito la creación de una instancia EC2 tipo r5.large en "
        "la región eu-central-1 con la clave prod-key, "
        "reglas de seguridad para los puertos 22, 443 y 8080, "
        "y las etiquetas Name=web-server, Environment=prod, "
        "asignando una IP pública",
        {
            "region": "eu-central-1", "instance_type": "r5.large",
            "key_name": "prod-key",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 8080, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
            "tags": [
                {"key": "Name", "value": "web-server"},
                {"key": "Environment", "value": "prod"},
            ],
            "associate_public_ip": True,
        },
    ),
    (
        "Creame un server en Sydney con la key default-key "
        "y el puerto 22 abierto, nada mas",
        {
            "region": "ap-southeast-2", "instance_type": "t3.micro",
            "key_name": "default-key",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
        },
    ),
    (
        "Levantame un m5.xlarge en California con la subnet subnet-4e5f6g7h, "
        "puertos 80 y 443 abiertos, y las tags Name=api-server, Team=backend",
        {
            "region": "us-west-1", "instance_type": "m5.xlarge",
            "subnet_id": "subnet-4e5f6g7h",
            "security_group_rules": [
                {"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
            "tags": [
                {"key": "Name", "value": "api-server"},
                {"key": "Team", "value": "backend"},
            ],
        },
    ),
    (
        "Necesito en Canadá un t3.micro con IP pública y tags: "
        "Name=web-server, Environment=staging, Owner=devops, "
        "y los puertos 22 y 443 abiertos",
        {
            "region": "ca-central-1", "instance_type": "t3.micro",
            "associate_public_ip": True,
            "tags": [
                {"key": "Name", "value": "web-server"},
                {"key": "Environment", "value": "staging"},
                {"key": "Owner", "value": "devops"},
            ],
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
        },
    ),
    (
        "Dame un t2.micro en us-east-1 asi nomas, lo basico",
        {"region": "us-east-1", "instance_type": "t2.micro"},
    ),
    (
        "Solicito una instancia tipo m5.large en la región us-east-2 "
        "con la clave admin-key y las etiquetas Name=db-server, "
        "Environment=prod, Team=infra, asignando IP pública",
        {
            "region": "us-east-2", "instance_type": "m5.large",
            "key_name": "admin-key",
            "tags": [
                {"key": "Name", "value": "db-server"},
                {"key": "Environment", "value": "prod"},
                {"key": "Team", "value": "infra"},
            ],
            "associate_public_ip": True,
        },
    ),
    (
        "Che, levantame un server en Frankfurt con la key prod-key, "
        "puertos 22, 443 y 3306 abiertos, subnet subnet-abc123, "
        "con IP pública y las tags Name=web-server, Environment=prod, "
        "CostCenter=cc-123, Project=migration, Team=platform",
        {
            "region": "eu-central-1", "instance_type": "m5.xlarge",
            "key_name": "prod-key",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 3306, "protocol": "tcp", "cidr": "10.0.0.0/16"},
            ],
            "subnet_id": "subnet-abc123",
            "associate_public_ip": True,
            "tags": [
                {"key": "Name", "value": "web-server"},
                {"key": "Environment", "value": "prod"},
                {"key": "CostCenter", "value": "cc-123"},
                {"key": "Project", "value": "migration"},
                {"key": "Team", "value": "platform"},
            ],
        },
    ),
    # --- New edge cases ---
    # Empty/minimal variants
    (
        "Server en Virginia",
        {"region": "us-east-1", "instance_type": "t3.micro"},
    ),
    (
        "Dame un server en Oregon",
        {"region": "us-west-2", "instance_type": "t3.micro"},
    ),
    (
        "Instancia en Frankfurt",
        {"region": "eu-central-1", "instance_type": "t3.micro"},
    ),
    # All params
    (
        "Necesito 3 instancias m5.xlarge en Virginia con la key deploy-key, "
        "puertos 22, 80 y 443 abiertos, subnet subnet-1234abcd, con IP pública, "
        "AMI ami-0abcdef1234567890, y tags Name=web-server, Environment=prod, "
        "Owner=devops, Team=infra, ManagedBy=terraform",
        {
            "region": "us-east-1", "instance_type": "m5.xlarge",
            "key_name": "deploy-key",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
            "subnet_id": "subnet-1234abcd",
            "associate_public_ip": True,
            "ami_id": "ami-0abcdef1234567890",
            "tags": [
                {"key": "Name", "value": "web-server"},
                {"key": "Environment", "value": "prod"},
                {"key": "Owner", "value": "devops"},
                {"key": "Team", "value": "infra"},
                {"key": "ManagedBy", "value": "terraform"},
            ],
            "min_count": 3,
            "max_count": 3,
        },
    ),
    (
        "Dame 2 servers c6i.2xlarge en Singapur con la key ci-key, "
        "puertos 443 y 8443 abiertos para 10.0.0.0/16, subnet subnet-5678efgh, "
        "sin IP pública, AMI ami-0e1f2a3b4c5d6e7f8, con los tags "
        "Name=api-server, Environment=staging, Team=backend, y CostCenter=cc-789",
        {
            "region": "ap-southeast-1", "instance_type": "c6i.2xlarge",
            "key_name": "ci-key",
            "security_group_rules": [
                {"port": 443, "protocol": "tcp", "cidr": "10.0.0.0/16"},
                {"port": 8443, "protocol": "tcp", "cidr": "10.0.0.0/16"},
            ],
            "subnet_id": "subnet-5678efgh",
            "associate_public_ip": False,
            "ami_id": "ami-0e1f2a3b4c5d6e7f8",
            "tags": [
                {"key": "Name", "value": "api-server"},
                {"key": "Environment", "value": "staging"},
                {"key": "Team", "value": "backend"},
                {"key": "CostCenter", "value": "cc-789"},
            ],
            "min_count": 2,
            "max_count": 2,
        },
    ),
    # Wrong-inferred / size-based without explicit type
    (
        "Necesito un server chico en Ohio",
        {"region": "us-east-2", "instance_type": "t3.micro"},
    ),
    (
        "Dame una instancia grande en Londres",
        {"region": "eu-west-2", "instance_type": "m5.xlarge"},
    ),
    (
        "Levantame algo potente en Tokio",
        {"region": "ap-northeast-1", "instance_type": "c6i.2xlarge"},
    ),
    (
        "Quiero un server económico en Canadá",
        {"region": "ca-central-1", "instance_type": "t2.micro"},
    ),
    # City-name only (inferred region)
    (
        "Server en Irlanda chico",
        {"region": "eu-west-1", "instance_type": "t3.micro"},
    ),
    (
        "Necesito una instancia en Sydney mediana",
        {"region": "ap-southeast-2", "instance_type": "m5.large"},
    ),
    # Spanglish / mixed language
    (
        "Dame un server en virginia con la key prod-key",
        {"region": "us-east-1", "instance_type": "t3.micro", "key_name": "prod-key"},
    ),
    (
        "I need a t3.medium server in ohio with public ip",
        {
            "region": "us-east-2", "instance_type": "t3.medium",
            "associate_public_ip": True,
        },
    ),
    (
        "Please create an EC2 instance m5.large in frankfurt, "
        "with key deploy-key and port 22 open",
        {
            "region": "eu-central-1", "instance_type": "m5.large",
            "key_name": "deploy-key",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
        },
    ),
    (
        "Che, need a server in sao paulo, t3.micro, with public ip, urgente",
        {
            "region": "sa-east-1", "instance_type": "t3.micro",
            "associate_public_ip": True,
        },
    ),
    # Very formal
    (
        "Sírvase aprovisionar una instancia EC2 de tipo r5.large en la región "
        "us-west-2 con la clave bastion-key, asignando una dirección IP pública",
        {
            "region": "us-west-2", "instance_type": "r5.large",
            "key_name": "bastion-key",
            "associate_public_ip": True,
        },
    ),
    (
        "Por este medio solicito la creación de una instancia EC2 tipo c6i.large "
        "en la región us-east-1, agradeceré incluir la clave vpn-key "
        "y las etiquetas Name=monitoring y Environment=prod",
        {
            "region": "us-east-1", "instance_type": "c6i.large",
            "key_name": "vpn-key",
            "tags": [
                {"key": "Name", "value": "monitoring"},
                {"key": "Environment", "value": "prod"},
            ],
        },
    ),
    # Multiple instance count variants
    (
        "Dame 5 instancias t3.medium en Irlanda para el proyecto scaling",
        {
            "region": "eu-west-1", "instance_type": "t3.medium",
            "min_count": 5, "max_count": 5,
        },
    ),
    # With AMI
    (
        "Levantame un c6i.large en Virginia con la AMI ami-0c55b159cbfafe1f0",
        {
            "region": "us-east-1", "instance_type": "c6i.large",
            "ami_id": "ami-0c55b159cbfafe1f0",
        },
    ),
    # Urgent / ALL CAPS
    (
        "CREAME URGENTE UN M5.LARGE EN VIRGINIA CON KEY PROD-KEY "
        "PUERTOS 22 Y 443 ABIERTOS IP PUBLICA YA",
        {
            "region": "us-east-1", "instance_type": "m5.large",
            "key_name": "prod-key",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
            "associate_public_ip": True,
        },
    ),
    # Random order params
    (
        "Con puertos 22 y 443, un m5.xlarge en Virginia, con IP pública, "
        "y la key prod-key, las tags Name=web-server Environment=prod",
        {
            "region": "us-east-1", "instance_type": "m5.xlarge",
            "key_name": "prod-key",
            "security_group_rules": [
                {"port": 22, "protocol": "tcp", "cidr": "0.0.0.0/0"},
                {"port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0"},
            ],
            "associate_public_ip": True,
            "tags": [
                {"key": "Name", "value": "web-server"},
                {"key": "Environment", "value": "prod"},
            ],
        },
    ),
]


def _select_ec2_edge(n):
    """Select up to n distinct edge cases."""
    sampled = random.sample(_EC2_EDGE, min(n, len(_EC2_EDGE)))
    return sampled


# ---------------------------------------------------------------------------
# restart_database generators
# ---------------------------------------------------------------------------

_RESTART_DB_TEMPLATES = [
    # === Casual / imperative ===
    "Reiniciá la base de datos {db_id} en {region}{failover}",
    "La DB {db_id} se colgó, reiniciala{location}{failover}",
    "Dale reboot a {db_id}{failover}",
    "Reiniciá {db_id} en {region}{failover}",
    "Dale, reiniciá {db_id}{failover}",
    # === "Che" / Rioplatense ===
    "Che, la {db_id} no responde, reiniciala urgente{location}{failover}",
    "Che, la base {db_id} se colgó, dale reboot{location}{failover}",
    "Che, reiniciá {db_id} en {region_name}{failover}",
    "Che, la {db_id} está muerta, reiniciala ya{location}{failover}",
    # === Neutral declarative ===
    "Por favor reiniciá la base {db_id} en {region}{failover}",
    "Solicito el reinicio de la instancia de base de datos {db_id} en la región {region}{failover}",
    "Necesito reiniciar {db_id} en {region_name}{failover}",
    "Podés reiniciar {db_id} en {region}{failover}?",
    "La base de datos {db_id} necesita un reinicio en {region}{failover}",
    "Me podés reiniciar {db_id} en {region_name}{failover}?",
    # === Very formal ===
    "Solicito el reinicio inmediato de la instancia de base de datos {db_id} "
    "ubicada en la región {region_name}{failover}",
    "Por favor, proceda a reiniciar la instancia de base de datos {db_id} "
    "en la región {region}{failover}",
    "Sírvase reiniciar la base de datos {db_id} en {region_name}{failover}",
    # === Spanglish / English-mixed ===
    "Reboot {db_id} in {region_name}{failover}",
    "Please restart the database {db_id} in {region}{failover}",
    "The {db_id} is down, restart it in {region_name}{failover}",
    # === Urgency / short ===
    "{db_id} down en {region_name}, reiniciala ya{failover}",
    "URGENTE: reiniciar {db_id} en {region}{failover}",
    "{db_id} caída, reboot urgente en {region}{failover}",
    # === Context-rich ===
    "La base {db_id} está corrupta, reiniciala en {region_name} con failover{failover}",
    "Se cayó {db_id} en {region}, reiniciala urgente con failover{failover}",
    "Estamos teniendo problemas con {db_id} en {region_name}, dale reboot{failover}",
]


def _gen_restart_db():
    """Generate one restart_database example (normal)."""
    db_id = random.choice(DB_INSTANCE_IDS)
    region = random.choice(REGIONS)
    args = {"db_instance_identifier": db_id, "region": region}
    extra_parts = []
    location_part = ""
    failover_part = ""

    # ~75% chance of force_failover
    if random.random() < 0.75:
        if random.random() < 0.55:
            args["force_failover"] = random.choice([True, False])
            if args.get("force_failover"):
                extra_parts.append("failover forzado")

    if extra_parts:
        failover_part = _detail_str(extra_parts)

    region_name = REGION_TO_NAME[region]

    template = random.choice(_RESTART_DB_TEMPLATES)
    user_msg = template.format(
        db_id=db_id, region=region, failover=failover_part,
        location="", region_name=region_name,
    )
    # Clean up
    user_msg = user_msg.replace("  ", " ").strip()
    return user_msg, args, "restart_database"


def _gen_restart_db_minimal():
    """Generate a restart_database with ONLY required params."""
    db_id = random.choice(DB_INSTANCE_IDS)
    region = random.choice(REGIONS)
    args = {"db_instance_identifier": db_id, "region": region}
    region_name = REGION_TO_NAME[region]

    templates = [
        "Reiniciá {db_id} en {region_name}",
        "{db_id} necesita un reinicio en {region}",
        "Dale reboot a {db_id} en {region_name}",
        "Reiniciá la base {db_id} en {region}",
        "Restart {db_id} in {region_name}",
    ]
    template = random.choice(templates)
    user_msg = template.format(db_id=db_id, region=region, region_name=region_name)
    return user_msg, args, "restart_database"


# Hand-crafted edge cases for restart_database
_RESTART_DB_EDGE = [
    # --- Original 15 (preserved) ---
    (
        "REINICIÁ YA LA PROD-DB-01 EN VIRGINIA CON FAILOVER FORZADO",
        {
            "db_instance_identifier": "prod-db-01",
            "region": "us-east-1",
            "force_failover": True,
        },
    ),
    (
        "La staging-mysql se quedó colgada, dale reboot urgente "
        "en Ohio sin failover",
        {
            "db_instance_identifier": "staging-mysql",
            "region": "us-east-2",
            "force_failover": False,
        },
    ),
    (
        "Solicito el reinicio inmediato de la instancia de base de datos "
        "analytics-postgres ubicada en la región eu-central-1, "
        "forzando la conmutación por error si es necesario",
        {
            "db_instance_identifier": "analytics-postgres",
            "region": "eu-central-1",
            "force_failover": True,
        },
    ),
    (
        "Che, la app-db-primary no da más, reiniciala en Oregon "
        "y que haga failover",
        {
            "db_instance_identifier": "app-db-primary",
            "region": "us-west-2",
            "force_failover": True,
        },
    ),
    (
        "Dale reboot a users-db en Singapur sin failover",
        {
            "db_instance_identifier": "users-db",
            "region": "ap-southeast-1",
            "force_failover": False,
        },
    ),
    (
        "La base de datos de logs en Tokio se colgó, reiniciala urgente",
        {
            "db_instance_identifier": "logs-db",
            "region": "ap-northeast-1",
        },
    ),
    (
        "Solicito el reinicio de ecommerce-db en sa-east-1 con failover forzado "
        "debido a una falla crítica en la replicación",
        {
            "db_instance_identifier": "ecommerce-db",
            "region": "sa-east-1",
            "force_failover": True,
        },
    ),
    (
        "Reiniciá la payments-db en Londres, pero sin failover por favor",
        {
            "db_instance_identifier": "payments-db",
            "region": "eu-west-2",
            "force_failover": False,
        },
    ),
    (
        "Che, la cms-db en Canadá no responde, reiniciala con failover",
        {
            "db_instance_identifier": "cms-db",
            "region": "ca-central-1",
            "force_failover": True,
        },
    ),
    (
        "Dale reboot a backup-db en Irlanda urgente",
        {
            "db_instance_identifier": "backup-db",
            "region": "eu-west-1",
        },
    ),
    (
        "La reporting-db está corrupta, reiniciala en Frankfurt con failover",
        {
            "db_instance_identifier": "reporting-db",
            "region": "eu-central-1",
            "force_failover": True,
        },
    ),
    (
        "Por favor reiniciá la base auth-db en California con failover forzado",
        {
            "db_instance_identifier": "auth-db",
            "region": "us-west-1",
            "force_failover": True,
        },
    ),
    (
        "La search-db en Virginia se colgó, dale reboot ya",
        {
            "db_instance_identifier": "search-db",
            "region": "us-east-1",
        },
    ),
    (
        "Reiniciá la audit-db en Sydney con failover forzado ya mismo",
        {
            "db_instance_identifier": "audit-db",
            "region": "ap-southeast-2",
            "force_failover": True,
        },
    ),
    (
        "Solicito el reinicio de inventory-db en la región us-west-2 "
        "sin failover, es mantenimiento planificado",
        {
            "db_instance_identifier": "inventory-db",
            "region": "us-west-2",
            "force_failover": False,
        },
    ),
    # --- New edge cases ---
    # Minimal / just the identifier
    (
        "Reiniciá prod-db-01",
        {
            "db_instance_identifier": "prod-db-01",
            "region": "us-east-1",
        },
    ),
    (
        "Restart ml-db",
        {
            "db_instance_identifier": "ml-db",
            "region": "us-east-1",
        },
    ),
    # Spanglish / mixed
    (
        "The database cms-db in virginia is down, restart it now",
        {
            "db_instance_identifier": "cms-db",
            "region": "us-east-1",
        },
    ),
    (
        "Che the ecommerce-db in sao paulo is dead, reiniciala urgente",
        {
            "db_instance_identifier": "ecommerce-db",
            "region": "sa-east-1",
        },
    ),
    (
        "The DB auth-db en california is not responding, reboot please",
        {
            "db_instance_identifier": "auth-db",
            "region": "us-west-1",
        },
    ),
    # Very formal
    (
        "Sírvase reiniciar la instancia de base de datos denominada "
        "prod-db-01 ubicada en la región us-east-1, "
        "forzando la conmutación por error",
        {
            "db_instance_identifier": "prod-db-01",
            "region": "us-east-1",
            "force_failover": True,
        },
    ),
    (
        "Por medio de la presente solicito el reinicio de la base de datos "
        "analytics-postgres en la región eu-central-1, sin failover",
        {
            "db_instance_identifier": "analytics-postgres",
            "region": "eu-central-1",
            "force_failover": False,
        },
    ),
    # ALL CAPS / urgency
    (
        "REINICIÁ YA LA PAYMENTS-DB EN LONDRES CON FAILOVER",
        {
            "db_instance_identifier": "payments-db",
            "region": "eu-west-2",
            "force_failover": True,
        },
    ),
    (
        "URGENTE: ML-DB EN OREGON CAÍDA, REINICIALA YA SIN FAILOVER",
        {
            "db_instance_identifier": "ml-db",
            "region": "us-west-2",
            "force_failover": False,
        },
    ),
    # City name only
    (
        "Reiniciá la base de datos principal en Frankfurt con failover",
        {
            "db_instance_identifier": "app-db-primary",
            "region": "eu-central-1",
            "force_failover": True,
        },
    ),
    (
        "Dale reboot a la base de staging en Ohio sin failover",
        {
            "db_instance_identifier": "staging-mysql",
            "region": "us-east-2",
            "force_failover": False,
        },
    ),
    # With extra context
    (
        "La base de datos de logs en Tokio se llenó y se colgó, "
        "reiniciala urgente con failover, necesitamos que vuelva ya",
        {
            "db_instance_identifier": "logs-db",
            "region": "ap-northeast-1",
            "force_failover": True,
        },
    ),
    (
        "Por issues de performance, reiniciá la inventory-db en us-west-2 "
        "sin failover, es mantenimiento programado",
        {
            "db_instance_identifier": "inventory-db",
            "region": "us-west-2",
            "force_failover": False,
        },
    ),
    # Questions
    (
        "Podés reiniciar la users-db en Ohio?",
        {
            "db_instance_identifier": "users-db",
            "region": "us-east-2",
        },
    ),
    (
        "Che, me podés reiniciar la app-db-primary?",
        {
            "db_instance_identifier": "app-db-primary",
            "region": "us-east-1",
        },
    ),
]


def _select_restart_db_edge(n):
    sampled = random.sample(_RESTART_DB_EDGE, min(n, len(_RESTART_DB_EDGE)))
    return sampled


# ---------------------------------------------------------------------------
# get_billing_alert generators
# ---------------------------------------------------------------------------

_BILLING_TEMPLATES = [
    # === Casual / imperative ===
    "Mostrame los gastos de este mes{service}",
    "Cuánto gastamos en {service} el mes pasado",
    "Dame el costo de {service} para {period}",
    "Consulta de billing del {period}{granularity}{service}",
    "Mostrame los costos{service}{period_details}",
    "Dame los gastos{service}{period_details}",
    "Mostrame el billing{service}{period_details}",
    "Cuánto estamos gastando{service}{period_details}",
    # === "Che" / Rioplatense ===
    "Che, cuánto gastamos{service} este período?",
    "Che, mostrame los costos{service}{period_details}",
    "Che, dame los números del billing{service}{period_details}",
    "Che, cuánta guita estamos quemando{service}{period_details}?",
    "Che, pasame los costos{service}{period_details}",
    # === Neutral declarative ===
    "Necesito el reporte de costos{service}{period_details}",
    "Solicito un informe de gastos{service}{period_details}",
    "Podés mostrarme los costos{service}{period_details}?",
    "Quiero ver los gastos{service}{period_details}",
    "Me pasás el detalle de costos{service}{period_details}?",
    "Necesito los costos desglosados{service}{period_details}",
    # === Very formal ===
    "Solicito un informe detallado de costos{service}{period_details}",
    "Por favor, sírvase proporcionar el reporte de gastos{service}{period_details}",
    "Solicito el reporte de costos correspondiente{service}{period_details}",
    "Agradeceré me remitan el detalle de gastos{service}{period_details}",
    # === Spanglish / English ===
    "Show me the costs{service}{period_details}",
    "I need the billing report{service}{period_details}",
    "Give me the cost breakdown{service}{period_details}",
    "What did we spend on {service}{period_details}?",
    # === Specific queries ===
    "Compará los costos de {service} entre {period} y el período anterior",
    "Mostrame el top de servicios por costo{period_details}",
    "Dame los costos por servicio{period_details}",
    "Cuánto nos está costando {service}{period_details}?",
    "Mostrame el resumen de costos{service}{period_details}",
    "Quiero ver los costos agregados por servicio{period_details}",
]


def _billing_period():
    """Pick a time period and return (NL text, start_date, end_date)."""
    choice = random.randint(0, 13)
    if choice == 0:
        start = TODAY.replace(day=1)
        return "este mes", start, TODAY
    elif choice == 1:
        first_this = TODAY.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return "el mes pasado", first_prev, last_prev
    elif choice == 2:
        return "enero 2026", date(2026, 1, 1), date(2026, 1, 31)
    elif choice == 3:
        q_start = TODAY - timedelta(days=90)
        return "el último trimestre", q_start, TODAY
    elif choice == 4:
        return "marzo a abril 2026", date(2026, 3, 1), date(2026, 4, 30)
    elif choice == 5:
        return "junio 2026", date(2026, 6, 1), date(2026, 6, 30)
    elif choice == 6:
        ytd = TODAY.replace(month=1, day=1)
        return "lo que va del año", ytd, TODAY
    elif choice == 7:
        end = TODAY - timedelta(days=TODAY.weekday() + 1)
        start = end - timedelta(days=6)
        return "la semana pasada", start, end
    elif choice == 8:
        return "el primer semestre de 2026", date(2026, 1, 1), date(2026, 6, 30)
    elif choice == 9:
        return "febrero 2026", date(2026, 2, 1), date(2026, 2, 28)
    elif choice == 10:
        return "abril 2026", date(2026, 4, 1), date(2026, 4, 30)
    elif choice == 11:
        end = TODAY
        start = end - timedelta(days=30)
        return "los últimos 30 días", start, end
    elif choice == 12:
        return "julio 2026", date(2026, 7, 1), TODAY
    else:
        return "el segundo trimestre de 2026", date(2026, 4, 1), date(2026, 6, 30)


def _gen_billing():
    """Generate one get_billing_alert example (normal)."""
    args = {}
    service_text = ""
    period_text = ""
    period_details_text = ""
    granularity_text = ""

    # ~85% get non-empty args
    has_params = random.random() < 0.85

    if has_params:
        # Add period ~85% of the time (almost always)
        if random.random() < 0.85:
            period_nl, start, end = _billing_period()
            args["time_period_start"] = start.isoformat()
            args["time_period_end"] = end.isoformat()
            period_text = period_nl
            period_details_text = f" del {period_nl}"

        # granularity ~50%
        if random.random() < 0.50:
            args["granularity"] = random.choice(["DAILY", "MONTHLY", "HOURLY"])
            granularity_text = f" con granularidad {args['granularity'].lower()}"

        # metrics ~45%
        if random.random() < 0.45:
            n_metrics = random.randint(1, 3)
            args["metrics"] = random.sample(BILLING_METRICS, n_metrics)

        # group_by_service ~45%
        if random.random() < 0.45:
            args["group_by_service"] = True
            svc = random.choice(SERVICES)
            service_text = f" en {svc}"
        else:
            service_text = ""

    template = random.choice(_BILLING_TEMPLATES)
    user_msg = template.format(
        service=service_text,
        period=period_text,
        granularity=granularity_text,
        period_details=period_details_text,
    )
    # Clean up
    user_msg = user_msg.replace("  ", " ").strip()
    return user_msg, args, "get_billing_alert"


def _gen_billing_minimal():
    """Generate a billing example with NO optional params."""
    templates = [
        "Mostrame los gastos",
        "Dame el billing",
        "Cuánto gastamos?",
        "Quiero ver los costos",
        "Mostrame los costos",
        "Necesito el reporte de gastos",
        "Billing report please",
        "Show me the costs",
    ]
    template = random.choice(templates)
    return template, {}, "get_billing_alert"


# Hand-crafted edge cases for get_billing_alert
_BILLING_EDGE = [
    # --- Original 10 (preserved) ---
    (
        "Mostrame los gastos",
        {},
    ),
    (
        "Cuánto gastamos en EC2 el mes pasado?",
        {
            "time_period_start": (TODAY.replace(day=1) - timedelta(days=1))
            .replace(day=1)
            .isoformat(),
            "time_period_end": (TODAY.replace(day=1) - timedelta(days=1))
            .isoformat(),
            "group_by_service": True,
        },
    ),
    (
        "Dame el costo de RDS para el último trimestre "
        "con granularidad mensual",
        {
            "time_period_start": (TODAY - timedelta(days=90)).isoformat(),
            "time_period_end": TODAY.isoformat(),
            "granularity": "MONTHLY",
            "group_by_service": True,
        },
    ),
    (
        "Solicito un informe detallado de gastos con desglose diario "
        "para el período de enero a marzo de 2026, "
        "incluyendo costos combinados y no combinados",
        {
            "time_period_start": "2026-01-01",
            "time_period_end": "2026-03-31",
            "granularity": "DAILY",
            "metrics": ["BlendedCost", "UnblendedCost"],
        },
    ),
    (
        "Che, cuánto estamos gastando en Lambda?",
        {
            "group_by_service": True,
        },
    ),
    (
        "Consulta de billing del mes de junio con granularidad diaria",
        {
            "time_period_start": "2026-06-01",
            "time_period_end": "2026-06-30",
            "granularity": "DAILY",
        },
    ),
    (
        "Necesito los costos de infraestructura de lo que va del año, "
        "agrupados por servicio, con costos amortizados",
        {
            "time_period_start": TODAY.replace(month=1, day=1).isoformat(),
            "time_period_end": TODAY.isoformat(),
            "group_by_service": True,
            "metrics": ["AmortizedCost"],
        },
    ),
    (
        "Cuánto gastamos en S3 la semana pasada con detalle diario",
        {
            "time_period_start": (
                TODAY - timedelta(days=TODAY.weekday() + 7)
            ).isoformat(),
            "time_period_end": (
                TODAY - timedelta(days=TODAY.weekday() + 1)
            ).isoformat(),
            "granularity": "DAILY",
            "group_by_service": True,
        },
    ),
    (
        "Mostrame todos los costos del primer semestre de 2026 "
        "con granularidad mensual, costos combinados y cantidad de uso",
        {
            "time_period_start": "2026-01-01",
            "time_period_end": "2026-06-30",
            "granularity": "MONTHLY",
            "metrics": ["BlendedCost", "UsageQuantity"],
        },
    ),
    (
        "Che, dame los costos por hora del mes de junio "
        "para todos los servicios",
        {
            "time_period_start": "2026-06-01",
            "time_period_end": "2026-06-30",
            "granularity": "HOURLY",
        },
    ),
    # --- New edge cases ---
    # Empty / no args
    (
        "Cuánto gastamos?",
        {},
    ),
    (
        "Dame el billing",
        {},
    ),
    # All params
    (
        "Necesito los costos de EC2 del mes de febrero de 2026 con "
        "granularidad diaria, costos combinados y no combinados, "
        "agrupados por servicio",
        {
            "time_period_start": "2026-02-01",
            "time_period_end": "2026-02-28",
            "granularity": "DAILY",
            "metrics": ["BlendedCost", "UnblendedCost"],
            "group_by_service": True,
        },
    ),
    (
        "Solicito el reporte completo de costos de la semana pasada "
        "con granularidad horaria, todas las métricas disponibles, "
        "agrupado por servicio",
        {
            "time_period_start": (
                TODAY - timedelta(days=TODAY.weekday() + 7)
            ).isoformat(),
            "time_period_end": (
                TODAY - timedelta(days=TODAY.weekday() + 1)
            ).isoformat(),
            "granularity": "HOURLY",
            "metrics": BILLING_METRICS,
            "group_by_service": True,
        },
    ),
    # Spanglish / mixed
    (
        "Show me the costs of EC2 for the last month",
        {
            "time_period_start": (TODAY.replace(day=1) - timedelta(days=1))
            .replace(day=1)
            .isoformat(),
            "time_period_end": (TODAY.replace(day=1) - timedelta(days=1))
            .isoformat(),
            "group_by_service": True,
        },
    ),
    (
        "Give me the billing for S3 last week daily",
        {
            "time_period_start": (
                TODAY - timedelta(days=TODAY.weekday() + 7)
            ).isoformat(),
            "time_period_end": (
                TODAY - timedelta(days=TODAY.weekday() + 1)
            ).isoformat(),
            "granularity": "DAILY",
            "group_by_service": True,
        },
    ),
    (
        "Che, how much did we spend on lambda este mes?",
        {
            "time_period_start": TODAY.replace(day=1).isoformat(),
            "time_period_end": TODAY.isoformat(),
            "group_by_service": True,
        },
    ),
    # Very formal
    (
        "Sírvase proporcionar el informe de costos correspondiente al mes "
        "de abril de 2026, con desglose diario, incluyendo costos combinados",
        {
            "time_period_start": "2026-04-01",
            "time_period_end": "2026-04-30",
            "granularity": "DAILY",
            "metrics": ["BlendedCost"],
        },
    ),
    (
        "Por este medio solicito el reporte de gastos de lo que va del año "
        "agrupado por servicio, con costos amortizados y no combinados",
        {
            "time_period_start": TODAY.replace(month=1, day=1).isoformat(),
            "time_period_end": TODAY.isoformat(),
            "group_by_service": True,
            "metrics": ["AmortizedCost", "NetUnblendedCost"],
        },
    ),
    # Multiple metrics
    (
        "Mostrame los costos combinados, no combinados y la cantidad "
        "de uso del último trimestre",
        {
            "time_period_start": (TODAY - timedelta(days=90)).isoformat(),
            "time_period_end": TODAY.isoformat(),
            "metrics": ["BlendedCost", "UnblendedCost", "UsageQuantity"],
        },
    ),
    # Net costs
    (
        "Dame los costos netos no combinados de DynamoDB "
        "del mes de julio",
        {
            "time_period_start": "2026-07-01",
            "time_period_end": "2026-07-24",
            "metrics": ["NetUnblendedCost"],
            "group_by_service": True,
        },
    ),
    # HOURLY granularity
    (
        "Necesito los costos por hora de SNS y SQS de febrero 2026",
        {
            "time_period_start": "2026-02-01",
            "time_period_end": "2026-02-28",
            "granularity": "HOURLY",
        },
    ),
    # Service list in text
    (
        "Cuánto gastamos en EC2, RDS y S3 el mes pasado?",
        {
            "time_period_start": (TODAY.replace(day=1) - timedelta(days=1))
            .replace(day=1)
            .isoformat(),
            "time_period_end": (TODAY.replace(day=1) - timedelta(days=1))
            .isoformat(),
            "group_by_service": True,
        },
    ),
    # 30 days
    (
        "Mostrame los costos de los últimos 30 días con granularidad diaria",
        {
            "time_period_start": (TODAY - timedelta(days=30)).isoformat(),
            "time_period_end": TODAY.isoformat(),
            "granularity": "DAILY",
        },
    ),
    # ALL CAPS
    (
        "DAME LOS COSTOS DE EC2 DE ENERO 2026 CON GRANULARIDAD DIARIA",
        {
            "time_period_start": "2026-01-01",
            "time_period_end": "2026-01-31",
            "granularity": "DAILY",
            "group_by_service": True,
        },
    ),
    # Second quarter
    (
        "Necesito los costos del segundo trimestre de 2026",
        {
            "time_period_start": "2026-04-01",
            "time_period_end": "2026-06-30",
        },
    ),
    # Q&A format
    (
        "Podés decirme cuánto gastamos en EC2 en lo que va del año?",
        {
            "time_period_start": TODAY.replace(month=1, day=1).isoformat(),
            "time_period_end": TODAY.isoformat(),
            "group_by_service": True,
        },
    ),
]


def _select_billing_edge(n):
    sampled = random.sample(_BILLING_EDGE, min(n, len(_BILLING_EDGE)))
    return sampled


# ---------------------------------------------------------------------------
# Multi-tool / ambiguous generators
# ---------------------------------------------------------------------------

_MULTI_TEMPLATES = [
    # (template_pool, tool_name, args_factory_or_static)
    # Billing-focused ambiguous
    (
        [
            "Cuánto nos está costando mantener la base de datos?",
            "Necesito ver los costos de los servidores que tenemos",
            "Mostrame los gastos de infraestructura del mes",
            "Che, cuánto estamos pagando de cloud este mes?",
            "Dame los costos de producción del último trimestre",
            "I need to see our cloud spending for this month",
            "Cuánto sale todo esto de cloud que tenemos?",
        ],
        "get_billing_alert",
        {},
    ),
    (
        [
            "Mostrame los costos de las bases de datos",
            "Cuánto estamos gastando en RDS?",
            "Che, cuánto sale la base de datos por mes?",
        ],
        "get_billing_alert",
        {"group_by_service": True},
    ),
    # EC2-focused ambiguous
    (
        [
            "Creame una instancia y decime cuánto sale",
            "Levantame un server nuevo y mostrame los costos actuales",
            "Dame un server en Virginia, el más chico",
            "Necesito una instancia EC2, la más económica",
            "Quiero contratar un servidor en la nube",
        ],
        "create_ec2_instance",
        {"region": "us-east-1", "instance_type": "t3.micro"},
    ),
    (
        [
            "Los servidores de producción están lentos, necesito más capacidad",
            "Estamos saturando los servers, levantame uno más",
            "Necesito escalar, agregame una instancia en producción",
        ],
        "create_ec2_instance",
        {"region": "us-east-1", "instance_type": "m5.large"},
    ),
    # DB-focused ambiguous
    (
        [
            "La base de datos está lenta, revisá los costos del último mes",
            "La DB principal se cayó, cuánto gastamos este mes?",
            "La base de producción anda mal, necesito info",
        ],
        "get_billing_alert",
        {
            "time_period_start": TODAY.replace(day=1).isoformat(),
            "time_period_end": TODAY.isoformat(),
        },
    ),
    (
        [
            "Necesito reiniciar el server de base de datos",
            "La base de datos no responde, dale reboot",
            "Se colgó la DB, reiniciala urgente",
            "La base de producción está caída",
        ],
        "restart_database",
        {
            "db_instance_identifier": "app-db-primary",
            "region": "us-east-1",
        },
    ),
    # EC2 + DB ambiguous
    (
        [
            "Los servers de la base de datos están lentos, revisá",
            "La base está corriendo lento, capaz necesita más recursos",
        ],
        "restart_database",
        {
            "db_instance_identifier": "prod-db-01",
            "region": "us-east-1",
        },
    ),
    # Billing + service reference
    (
        [
            "Mostrame los gastos de las instancias EC2 que tenemos en Virginia",
            "Cuánto estamos pagando por los servers web?",
            "Dame un reporte de costos de los servidores que tenemos en producción",
        ],
        "get_billing_alert",
        {"group_by_service": True},
    ),
    # Other
    (
        [
            "Che, cuánta guita estamos gastando en la base de datos?",
            "Pásame los costos de la base de datos",
        ],
        "get_billing_alert",
        {"group_by_service": True},
    ),
    (
        [
            "Todo está lento, creo que la DB se cayó",
            "No puedo conectar a la base, debe estar caída",
        ],
        "restart_database",
        {
            "db_instance_identifier": "prod-db-01",
            "region": "us-east-1",
        },
    ),
]

# Hand-crafted multi-tool examples (original 10 + new ones)
_MULTI_HAND_CRAFTED = [
    # --- Original 10 (preserved) ---
    (
        "Necesito ver los costos de la base de datos de producción",
        "get_billing_alert",
        {"group_by_service": True, "metrics": ["BlendedCost"]},
    ),
    (
        "La base de datos está lenta, revisá los costos del último mes",
        "get_billing_alert",
        {
            "time_period_start": (TODAY.replace(day=1) - timedelta(days=1))
            .replace(day=1)
            .isoformat(),
            "time_period_end": (TODAY.replace(day=1) - timedelta(days=1))
            .isoformat(),
        },
    ),
    (
        "Creame una instancia y decime cuánto sale",
        "create_ec2_instance",
        {"region": "us-east-1", "instance_type": "t3.micro"},
    ),
    (
        "Mostrame los gastos de las instancias EC2 que tenemos en Virginia",
        "get_billing_alert",
        {"group_by_service": True, "metrics": ["BlendedCost", "UnblendedCost"]},
    ),
    (
        "Reiniciá la base de datos y revisá si hay costos elevados",
        "restart_database",
        {
            "db_instance_identifier": "prod-db-01",
            "region": "us-east-1",
        },
    ),
    (
        "Dame un reporte de costos de los servidores que tenemos en producción",
        "get_billing_alert",
        {"group_by_service": True, "metrics": ["BlendedCost"]},
    ),
    (
        "La DB principal se cayó, cuánto gastamos este mes?",
        "get_billing_alert",
        {
            "time_period_start": TODAY.replace(day=1).isoformat(),
            "time_period_end": TODAY.isoformat(),
        },
    ),
    (
        "Levantame un server nuevo y mostrame los costos actuales",
        "create_ec2_instance",
        {"region": "us-east-1", "instance_type": "t3.medium"},
    ),
    (
        "Che, cuánta guita estamos gastando en la base de datos?",
        "get_billing_alert",
        {"group_by_service": True},
    ),
    (
        "Necesito reiniciar el server de base de datos",
        "restart_database",
        {
            "db_instance_identifier": "app-db-primary",
            "region": "us-east-1",
        },
    ),
    # --- New hand-crafted multi-tool ---
    (
        "No sé si la DB está caída o es un tema de costos, revisá",
        "get_billing_alert",
        {
            "time_period_start": TODAY.replace(day=1).isoformat(),
            "time_period_end": TODAY.isoformat(),
        },
    ),
    (
        "Se cayó todo, revisá los servers y la base",
        "restart_database",
        {
            "db_instance_identifier": "prod-db-01",
            "region": "us-east-1",
        },
    ),
    (
        "Quiero saber cuánto gastamos y si podemos agregar un server más",
        "get_billing_alert",
        {"group_by_service": True},
    ),
    (
        "Che, la base no anda y además estamos gastando mucha guita, revisá",
        "get_billing_alert",
        {
            "time_period_start": TODAY.replace(day=1).isoformat(),
            "time_period_end": TODAY.isoformat(),
        },
    ),
    (
        "Los servidores web están al palo, necesitamos más capacidad "
        "y saber cuánto estamos gastando",
        "create_ec2_instance",
        {"region": "us-east-1", "instance_type": "m5.xlarge"},
    ),
    (
        "No puedo acceder a la base de datos de usuarios, "
        "y necesito ver los costos de este mes",
        "restart_database",
        {
            "db_instance_identifier": "users-db",
            "region": "us-east-1",
        },
    ),
    (
        "El dashboard de billing no carga, dame los números de este mes "
        "y revisá si la base está bien",
        "get_billing_alert",
        {
            "time_period_start": TODAY.replace(day=1).isoformat(),
            "time_period_end": TODAY.isoformat(),
        },
    ),
    (
        "Che, tenemos un pico de gasto en EC2 y la base está lenta",
        "get_billing_alert",
        {"group_by_service": True, "metrics": ["BlendedCost"]},
    ),
    (
        "Preciso una instancia nueva en Oregon y el reporte de costos "
        "del último mes",
        "create_ec2_instance",
        {"region": "us-west-2", "instance_type": "t3.medium"},
    ),
    (
        "La base de datos de logs no responde, cuánto estamos "
        "gastando en infra?",
        "restart_database",
        {
            "db_instance_identifier": "logs-db",
            "region": "ap-northeast-1",
        },
    ),
    (
        "Se cayó la base de producción, necesito saber los costos "
        "del último trimestre para justificar el presupuesto",
        "restart_database",
        {
            "db_instance_identifier": "prod-db-01",
            "region": "us-east-1",
        },
    ),
    (
        "No me andan las queries, debe ser la base. "
        "Aparte, mostrame los costos de EC2 del mes",
        "restart_database",
        {
            "db_instance_identifier": "app-db-primary",
            "region": "us-east-1",
        },
    ),
    (
        "Estamos teniendo problemas de performance. Necesito escalar "
        "y entender los costos actuales",
        "create_ec2_instance",
        {"region": "us-east-1", "instance_type": "m5.large"},
    ),
    (
        "Che, todo está lento hoy. Revisá los servers y la base",
        "restart_database",
        {
            "db_instance_identifier": "app-db-primary",
            "region": "us-east-1",
        },
    ),
    (
        "I think the database is down in virginia, "
        "and I need to see this month's costs",
        "restart_database",
        {
            "db_instance_identifier": "prod-db-01",
            "region": "us-east-1",
        },
    ),
]


def _gen_multi_tool(count):
    """Generate multi-tool/ambiguous examples from templates and hand-crafted."""
    examples = []

    # Add all hand-crafted
    for user_msg, tool, args in _MULTI_HAND_CRAFTED:
        examples.append((user_msg, tool, args))

    # Generate from templates
    while len(examples) < count:
        templates, tool, args = random.choice(_MULTI_TEMPLATES)
        user_msg = random.choice(templates)
        # If args is a dict with static values or empty, use directly
        # If we need dynamic args, generate them here
        final_args = dict(args) if isinstance(args, dict) else {}
        examples.append((user_msg, tool, final_args))

    # Shuffle and return requested count
    random.shuffle(examples)
    return examples[:count]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_dataset(records, tool_defs):
    """Validate all records against tool definitions.

    Returns list of error strings (empty = all valid).
    """
    # Build lookup: tool name -> properties with their enums
    schemas = {}
    for td in tool_defs:
        schemas[td["name"]] = td["parameters"]

    errors = []

    for i, rec in enumerate(records):
        try:
            tc = rec["messages"][2]["tool_calls"][0]["function"]
        except (KeyError, IndexError, TypeError):
            errors.append(f"Record {i}: malformed structure")
            continue

        tool_name = tc["name"]

        # Parse arguments JSON
        try:
            args = json.loads(tc["arguments"])
        except json.JSONDecodeError as e:
            errors.append(f"Record {i} ({tool_name}): invalid JSON arguments: {e}")
            continue

        if not isinstance(args, dict):
            errors.append(f"Record {i} ({tool_name}): arguments not a dict")
            continue

        if tool_name not in schemas:
            errors.append(f"Record {i}: unknown tool '{tool_name}'")
            continue

        props = schemas[tool_name].get("properties", {})

        # Check for unknown params
        for key in args:
            if key not in props:
                errors.append(f"Record {i} ({tool_name}): unknown param '{key}'")

        # Check enum values
        for key, val in args.items():
            if key not in props:
                continue
            prop = props[key]
            if "enum" in prop:
                if isinstance(val, list):
                    # Array of enums (e.g., metrics)
                    for v in val:
                        if v not in prop["enum"]:
                            errors.append(
                                f"Record {i} ({tool_name}): invalid enum value "
                                f"{key}={v}, valid: {prop['enum']}"
                            )
                elif isinstance(val, str) and val not in prop["enum"]:
                    errors.append(
                        f"Record {i} ({tool_name}): invalid enum value "
                        f"{key}={val}, valid: {prop['enum']}"
                    )

            # Check nested objects with enums (security_group_rules)
            if key == "security_group_rules" and isinstance(val, list):
                for j, rule in enumerate(val):
                    if not isinstance(rule, dict):
                        errors.append(
                            f"Record {i} ({tool_name}): SG rule {j} not a dict"
                        )
                        continue
                    # Check protocol enum in nested rules
                    proto = rule.get("protocol")
                    if proto and proto not in PROTOCOLS:
                        errors.append(
                            f"Record {i} ({tool_name}): SG rule {j} "
                            f"invalid protocol '{proto}'"
                        )
                    # Check port is integer
                    port = rule.get("port")
                    if port is not None and not isinstance(port, int):
                        errors.append(
                            f"Record {i} ({tool_name}): SG rule {j} "
                            f"port not an integer: {port}"
                        )
                    # Check cidr is present
                    if "cidr" not in rule:
                        errors.append(
                            f"Record {i} ({tool_name}): SG rule {j} missing cidr"
                        )

            # Check tags structure
            if key == "tags" and isinstance(val, list):
                for j, tag in enumerate(val):
                    if not isinstance(tag, dict):
                        errors.append(
                            f"Record {i} ({tool_name}): tag {j} not a dict"
                        )
                        continue
                    if "key" not in tag or "value" not in tag:
                        errors.append(
                            f"Record {i} ({tool_name}): tag {j} missing key or value"
                        )

            # Check that min_count < max_count if both present
            if "min_count" in args and "max_count" in args:
                if args["min_count"] > args["max_count"]:
                    errors.append(
                        f"Record {i} ({tool_name}): min_count > max_count"
                    )

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def load_tool_definitions(path):
    """Load and validate tool definitions JSON."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_dataset():
    """Generate the full dataset and write to output file."""
    # Load tool defs (for validation)
    tool_defs = load_tool_definitions(TOOL_DEFS_PATH)
    tool_names = {t["name"] for t in tool_defs}
    print(f"Loaded {len(tool_defs)} tool definitions: {', '.join(sorted(tool_names))}")

    # Distribution targets (total ~8000)
    EC2_TOTAL = 3600
    EC2_EDGE = 120
    EC2_ALL_PARAMS = 120
    EC2_MINIMAL = 120
    DB_TOTAL = 2400
    DB_EDGE = 80
    DB_MINIMAL = 80
    BILLING_TOTAL = 1500
    BILLING_EDGE = 60
    BILLING_MINIMAL = 60
    MULTI_TOTAL = 500

    records = []

    # --- create_ec2_instance ---
    ec2_normal = EC2_TOTAL - EC2_EDGE - EC2_ALL_PARAMS - EC2_MINIMAL
    for _ in range(ec2_normal):
        user_msg, args, tool = _gen_ec2()
        records.append(_make_record(user_msg, tool, args))
    for user_msg, args in _select_ec2_edge(EC2_EDGE):
        records.append(_make_record(user_msg, "create_ec2_instance", args))
    for _ in range(EC2_ALL_PARAMS):
        user_msg, args, tool = _gen_ec2_all_params()
        records.append(_make_record(user_msg, tool, args))
    for _ in range(EC2_MINIMAL):
        user_msg, args, tool = _gen_ec2_minimal()
        records.append(_make_record(user_msg, tool, args))
    print(
        f"  Generated {EC2_TOTAL} create_ec2_instance examples "
        f"({ec2_normal} normal + {EC2_EDGE} edge + {EC2_ALL_PARAMS} all-params + "
        f"{EC2_MINIMAL} minimal)"
    )

    # --- restart_database ---
    db_normal = DB_TOTAL - DB_EDGE - DB_MINIMAL
    for _ in range(db_normal):
        user_msg, args, tool = _gen_restart_db()
        records.append(_make_record(user_msg, tool, args))
    for user_msg, args in _select_restart_db_edge(DB_EDGE):
        records.append(_make_record(user_msg, "restart_database", args))
    for _ in range(DB_MINIMAL):
        user_msg, args, tool = _gen_restart_db_minimal()
        records.append(_make_record(user_msg, tool, args))
    print(
        f"  Generated {DB_TOTAL} restart_database examples "
        f"({db_normal} normal + {DB_EDGE} edge + {DB_MINIMAL} minimal)"
    )

    # --- get_billing_alert ---
    billing_normal = BILLING_TOTAL - BILLING_EDGE - BILLING_MINIMAL
    for _ in range(billing_normal):
        user_msg, args, tool = _gen_billing()
        records.append(_make_record(user_msg, tool, args))
    for user_msg, args in _select_billing_edge(BILLING_EDGE):
        records.append(_make_record(user_msg, "get_billing_alert", args))
    for _ in range(BILLING_MINIMAL):
        user_msg, args, tool = _gen_billing_minimal()
        records.append(_make_record(user_msg, tool, args))
    print(
        f"  Generated {BILLING_TOTAL} get_billing_alert examples "
        f"({billing_normal} normal + {BILLING_EDGE} edge + {BILLING_MINIMAL} minimal)"
    )

    # --- multi-tool ---
    multi_examples = _gen_multi_tool(MULTI_TOTAL)
    for user_msg, tool, args in multi_examples:
        records.append(_make_record(user_msg, tool, args))
    print(f"  Generated {MULTI_TOTAL} multi-tool/ambiguous examples")

    # Shuffle everything
    random.shuffle(records)
    print(f"  Shuffled {len(records)} total examples")

    # --- Validation ---
    print()
    print("=" * 60)
    print("VALIDATION")
    print("=" * 60)
    validation_errors = validate_dataset(records, tool_defs)
    if validation_errors:
        print(f"  FAILED: {len(validation_errors)} validation error(s):")
        for err in validation_errors[:20]:  # Show first 20
            print(f"    - {err}")
        if len(validation_errors) > 20:
            print(f"    ... and {len(validation_errors) - 20} more errors")
    else:
        print("  All records OK — no validation errors")

    # Write output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Summary
    per_tool = {}
    for rec in records:
        tool = rec["messages"][2]["tool_calls"][0]["function"]["name"]
        per_tool[tool] = per_tool.get(tool, 0) + 1

    print()
    print("=" * 60)
    print("DATASET GENERATION SUMMARY")
    print("=" * 60)
    print(f"  Total examples: {len(records)}")
    for tool in sorted(per_tool):
        pct = per_tool[tool] / len(records) * 100
        print(f"    {tool}: {per_tool[tool]} ({pct:.1f}%)")
    print(f"  Output path: {OUTPUT_PATH}")
    print("=" * 60)


def main():
    random.seed(SEED)
    generate_dataset()


if __name__ == "__main__":
    main()
