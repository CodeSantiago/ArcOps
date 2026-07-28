"""Test mcp_server's generate_tool_call vs direct"""
import sys, json
sys.path.insert(0, ".")
from scripts.mcp_server import generate_tool_call

result = generate_tool_call("Creame un server t3.micro en us-east-1 con puerto 80")
print("MCP:", json.dumps(result, ensure_ascii=False))
