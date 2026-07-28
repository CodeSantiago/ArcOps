"""Check structure of eval_report.json"""
import json
d = json.load(open("checkpoints/eval_report.json"))
print("Keys:", list(d.keys()))
if "results" in d and d["results"]:
    r = d["results"][0]
    print("Result keys:", list(r.keys()))
    print(json.dumps(r, indent=2, default=str)[:800])
elif isinstance(d, list):
    print("It's a list of", len(d))
    print(json.dumps(d[0], indent=2, default=str)[:500])
