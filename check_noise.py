"""Check noise examples in dataset."""
import json
data = [json.loads(l) for l in open("data/training_dataset.jsonl")]
noise = 0
for ex in data:
    for m in ex.get("messages", []):
        if m.get("role") == "user":
            c = m.get("content", "")
            if "log the event" in c or "notify me" in c or "make sure" in c or "log everything" in c:
                noise += 1
                break
print(f"Noise examples: {noise} / {len(data)}")
# Also check a sample
for ex in data:
    for m in ex.get("messages", []):
        if m.get("role") == "user" and "log the event" in m.get("content", ""):
            print(f"Example: {m['content'][:100]}")
            break
    break
