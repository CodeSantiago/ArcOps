"""Check if eval report shows 100% and if there's a data leak."""
import json, os

report = "checkpoints/eval_report.json"
if not os.path.exists(report):
    print("NO EVAL REPORT FOUND")
    exit()

d = json.load(open(report))
results = d.get("results", [])
summary = d.get("summary", d)

print(f"Examples evaluated: {len(results)}")
print(f"Exact match: {summary.get('exact_match_accuracy', summary.get('exact_match','?'))}")
print(f"Tool accuracy: {summary.get('tool_name_accuracy','?')}")
print(f"Field accuracy: {summary.get('field_accuracy_mean','?')}")

# Check if ALL results are perfect
all_perfect = all(r.get("exact_match", False) for r in results)
print(f"\nAll exact matches: {all_perfect}")
if all_perfect:
    print("SUSPICIOUS: 100% exact match rate")

# Check dataset split sizes
data_file = "data/training_dataset.jsonl"
if os.path.exists(data_file):
    with open(data_file) as f:
        lines = sum(1 for _ in f)
    print(f"\nDataset size: {lines} examples")
    print(f"Expected test split (10%): ~{lines // 10}")
    
    # Show a few results to sanity check
    print("\nSample results (first 5):")
    for r in results[:5]:
        ref = r.get("expected", {})
        pred = r.get("predicted", {})
        em = "✓" if r.get("exact_match") else "✗"
        print(f"  {em} expected={ref.get('name')}  predicted={pred.get('name')}")
