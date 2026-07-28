"""Audit all fields in the current dataset."""
import json
from collections import Counter

data = [json.loads(l) for l in open("data/training_dataset.jsonl")]
tools = {}

for ex in data:
    for m in ex.get("messages", []):
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls", []) or []:
                fn = tc.get("function", tc)
                name = fn.get("name")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except: args = {}
                if name not in tools:
                    tools[name] = {}
                for k, v in args.items():
                    if k not in tools[name]:
                        tools[name][k] = {"count": 0, "types": set(), "example": None}
                    tools[name][k]["count"] += 1
                    tools[name][k]["types"].add(type(v).__name__)
                    if tools[name][k]["example"] is None:
                        tools[name][k]["example"] = repr(v)[:60]

for tool, fields in sorted(tools.items()):
    print(f"\n[{tool}]")
    for field, info in sorted(fields.items()):
        types = ",".join(sorted(info["types"]))
        pct = 100 * info["count"] / sum(f["count"] for f in fields.values())
        flag = ""
        if info["count"] < 50:
            flag = "  <-- LOW COUNT"
        if len(info["types"]) > 1:
            flag += "  <-- MULTIPLE TYPES"
        if flag:
            flag = f"  \033[93m{flag}\033[0m"
        print(f"  {field:30s} x{info['count']:5d} ({pct:5.1f}%)  {types:20s}  {info['example']}{flag}")
