"""Add noise examples to dataset - fix log_event hallucination."""
import json, random

DATA = "data/training_dataset.jsonl"
random.seed(42)

data = [json.loads(l) for l in open(DATA)]

noise_phrases = [
    "but also log the event", "and log everything please", "make sure to log it",
    "also notify the team", "and send me an alert", "please log all details",
    "and keep a record", "make sure it is logged", "log this for auditing",
    "please monitor this closely", "and alert me when done", "track this carefully",
]

added = 0
for _ in range(500):
    ex = random.choice(data)
    for m in ex["messages"]:
        if m["role"] == "user":
            noise = random.choice(noise_phrases)
            m["content"] = m["content"].rstrip(". ") + ", " + noise
            added += 1
            break

random.shuffle(data)
with open(DATA, "w") as f:
    for ex in data:
        f.write(json.dumps(ex, ensure_ascii=False) + "\n")

noise_count = sum(1 for ex in data for m in ex["messages"] if m.get("role")=="user" and any(p in m.get("content","") for p in noise_phrases))
print(f"Added: {added}")
print(f"Noise in dataset: {noise_count}/{len(data)}")
