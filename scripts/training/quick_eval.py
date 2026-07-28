"""Quick evaluation — tests a small subset for fast iteration.

Usage:
    uv run python scripts/training/quick_eval.py --checkpoint checkpoints/final --samples 50
"""
import argparse, json, random, sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.training.eval import generate_tool_call, compute_exact_match, compute_field_accuracy, compute_tool_name_accuracy

def load_test_set(config_path, n_samples=50):
    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f)
    data_file = config["data"]["train_file"]
    seed = config["data"].get("seed", 42)
    
    with open(data_file) as f:
        data = [json.loads(l) for l in f]
    
    random.seed(seed + 1)  # Different seed from training
    random.shuffle(data)
    return data[:n_samples]

def main():
    parser = argparse.ArgumentParser(description="Quick eval on a subset")
    parser.add_argument("--checkpoint", default="checkpoints/final")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--config", default="scripts/training/quick_config.yaml")
    args = parser.parse_args()
    
    print(f"Loading {args.samples} test samples...")
    test_set = load_test_set(args.config, args.samples)
    
    exact = correct_tool = total_fields = correct_fields = 0
    
    for i, ex in enumerate(test_set):
        # Find the user prompt and expected response
        user_msg = ""
        expected = {}
        for m in ex["messages"]:
            if m["role"] == "user":
                user_msg = m["content"]
            elif m["role"] == "assistant":
                for tc in m.get("tool_calls", []):
                    fn = tc.get("function", tc)
                    expected = {"name": fn.get("name"), "arguments": fn.get("arguments", {})}
                    if isinstance(expected["arguments"], str):
                        expected["arguments"] = json.loads(expected["arguments"])
        
        if not user_msg or not expected:
            continue
        
        # Generate prediction
        result = generate_tool_call(user_msg)
        if "error" in result:
            print(f"  [{i+1}] ERROR: {result['error']}")
            continue
        
        predicted = {"name": result.get("name"), "arguments": result.get("arguments", {})}
        
        # Compare
        em = compute_exact_match(predicted, expected)
        tn = compute_tool_name_accuracy(predicted.get("name"), expected.get("name"))
        fa = compute_field_accuracy(predicted.get("arguments", {}), expected.get("arguments", {}))
        
        exact += 1 if em else 0
        correct_tool += tn
        total_fields += 1
        correct_fields += fa
        
        mark = "✓" if em else "✗"
        print(f"  [{i+1}] {mark} tool={predicted.get('name')}  fields={fa:.0%}")
    
    n = len(test_set)
    print(f"\n{'='*40}")
    print(f"  Samples:    {n}")
    print(f"  Exact match: {exact/n:.1%}")
    print(f"  Tool acc:    {correct_tool/n:.1%}")
    print(f"  Fields:      {correct_fields/n:.1%}")
    print(f"  Time:        ~{n * 30}s (estimate)")
    print(f"{'='*40}")

if __name__ == "__main__":
    main()
