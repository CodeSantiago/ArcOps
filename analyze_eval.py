"""Analyze eval report per-field accuracy."""
import json, sys
from collections import Counter

data = json.load(open(sys.argv[1]))
results = data.get("results", [])

per_tool = {}  # tool -> {field: {hits, total}}
all_fields = {}

for r in results:
    ref = r.get("expected", {})
    pred = r.get("predicted", {})
    ref_args = ref.get("arguments", {})
    pred_args = pred.get("arguments", {})
    tool = ref.get("name", "unknown")
    
    if tool not in per_tool:
        per_tool[tool] = {}
    
    for key in ref_args:
        if key not in all_fields:
            all_fields[key] = {"hits": 0, "total": 0, "tools": set()}
        if key not in per_tool[tool]:
            per_tool[tool][key] = {"hits": 0, "total": 0}
        
        all_fields[key]["total"] += 1
        per_tool[tool][key]["total"] += 1
        all_fields[key]["tools"].add(tool)
        
        if key in pred_args and pred_args[key] == ref_args[key]:
            all_fields[key]["hits"] += 1
            per_tool[tool][key]["hits"] += 1

print(f"\nAnalyzing {len(results)} examples\n")
print("=" * 60)

for tool in sorted(per_tool.keys()):
    print(f"\n  [{tool}]")
    for field in sorted(per_tool[tool].keys()):
        d = per_tool[tool][field]
        pct = d["hits"] / d["total"] * 100 if d["total"] else 0
        bar = "#" * int(pct / 4)
        print(f"    {field:30s} {pct:>6.1f}%  {d['hits']:>3d}/{d['total']:<3d}  {bar}")

print(f"\n{'='*60}")
print(f"\n  {'Field':30s} {'Accuracy':>8s} {'Hits':>6s} {'Total':>6s}  {'Tools'}")
print(f"  {'-'*30} {'-'*8} {'-'*6} {'-'*6}  {'-'*10}")
for field in sorted(all_fields.keys(), key=lambda f: all_fields[f]["hits"]/max(all_fields[f]["total"],1)):
    d = all_fields[field]
    pct = d["hits"] / d["total"] * 100 if d["total"] else 0
    bar = "#" * int(pct / 4)
    tools_str = ", ".join(sorted(d["tools"]))
    print(f"  {field:30s} {pct:>7.1f}%  {d['hits']:>3d}/{d['total']:<3d}  {bar}  [{tools_str}]")

overall_hits = sum(d["hits"] for d in all_fields.values())
overall_total = sum(d["total"] for d in all_fields.values())
print(f"\n  Overall field accuracy: {overall_hits}/{overall_total} = {overall_hits/overall_total*100:.1f}%\n")
