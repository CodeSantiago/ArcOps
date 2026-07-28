"""Auditar dataset de fine-tuning para tool-calling."""
import json, sys
from collections import defaultdict, Counter

def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  [!] Line {line_num}: {e}")
    return rows

def extract_tool_calls(row):
    calls = []
    if "messages" in row:
        for msg in row["messages"]:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []) or []:
                    fn = tc.get("function", tc)
                    name = fn.get("name")
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try: args = json.loads(args)
                        except: args = {}
                    if name:
                        calls.append({"name": name, "arguments": args or {}})
    return calls

def type_name(value):
    if isinstance(value, bool): return "bool"
    if isinstance(value, int): return "int"
    if isinstance(value, str): return "str"
    if isinstance(value, list): return f"list[{len(value)} items]"
    if isinstance(value, dict): return "dict"
    if value is None: return "null"
    return type(value).__name__

def audit(rows, target_fields=None):
    total_calls = 0
    per_tool = Counter()
    presence = defaultdict(int)
    absence = defaultdict(int)
    types = defaultdict(Counter)
    values = defaultdict(Counter)

    for row in rows:
        for call in extract_tool_calls(row):
            total_calls += 1
            per_tool[call["name"]] += 1
            args = call.get("arguments") or {}
            fields = target_fields or args.keys()
            for f in fields:
                if f in args and args[f] is not None:
                    presence[f] += 1
                    v = args[f]
                    types[f][type_name(v)] += 1
                    if isinstance(v, bool) or isinstance(v, int):
                        values[f][repr(v)] += 1
                    elif isinstance(v, str) and len(v) <= 50:
                        values[f][v] += 1
                else:
                    absence[f] += 1
    return {"total": total_calls, "per_tool": per_tool, "presence": presence, "absence": absence, "types": types, "values": values}

def main():
    path = sys.argv[1]
    target = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    rows = load_jsonl(path)
    print(f"Loaded {len(rows)} examples")
    r = audit(rows, target)
    if r["total"] == 0:
        print("No tool calls found. Example row:", json.dumps(rows[0], indent=2)[:500] if rows else "empty")
        return
    print(f"\nTotal tool calls: {r['total']}")
    for name, count in r["per_tool"].most_common():
        print(f"  {name}: {count} ({100*count/r['total']:.1f}%)")
    fields = target or sorted(r["presence"].keys())
    for f in fields:
        p = r["presence"].get(f, 0)
        a = r["absence"].get(f, 0)
        seen = p + a
        if seen == 0:
            print(f"\n  [!] Field '{f}' never appears")
            continue
        print(f"\n  [{f}] present={p}/{seen} ({100*p/seen:.1f}%)")
        t = r["types"].get(f, Counter())
        if len(t) > 1:
            print(f"    TYPE MISMATCH: {dict(t)}")
        else:
            print(f"    type: {list(t.keys())[0] if t else '?'}")
        vals = r["values"].get(f)
        if vals and len(vals) <= 20:
            total_v = sum(vals.values())
            print(f"    values ({len(vals)}):")
            for v, c in vals.most_common():
                print(f"      {str(v)[:30]:30s} x{c:5d} ({100*c/total_v:.1f}%)")

if __name__ == "__main__":
    main()
