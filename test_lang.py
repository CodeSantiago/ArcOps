"""Test model in English and Spanish"""
import sys, json
sys.path.insert(0, ".")
from scripts.mcp_server import generate_tool_call

tests = [
    ("spanish", "Creame un server t3.micro en us-east-1 con puerto 80"),
    ("english", "Create a t3.micro server in us-east-1 with port 80 open"),
    ("english2", "Restart the production database in us-west-2"),
    ("english3", "How much did we spend this month on AWS?"),
]

for lang, prompt in tests:
    result = generate_tool_call(prompt)
    ok = "✅" if "error" not in result else "❌"
    print(f"{ok} [{lang}] {prompt[:50]}")
    print(f"   -> {json.dumps(result, ensure_ascii=False)}\n")
