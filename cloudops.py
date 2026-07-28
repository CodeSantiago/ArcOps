#!/usr/bin/env python3
"""ArcOps — Natural language → AWS JSON tool calls. 100% local."""
import json, os, sys, socket, threading, time, signal, subprocess
from pathlib import Path

CACHE = Path.home() / ".arcops" / "server.port"
PID_FILE = Path.home() / ".arcops" / "server.pid"

# ── Direct inference (works everywhere including pip install) ───────────
_model, _tokenizer = None, None

def infer(prompt: str) -> dict:
    global _model, _tokenizer
    if _model is None:
        print("* Loading model (first time ~30s)...")
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from peft import PeftModel
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
        model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-7B-Instruct", quantization_config=bnb, device_map="auto", torch_dtype=torch.bfloat16)
        model = PeftModel.from_pretrained(model, "CodeSantiago/arcops", offload_folder="/tmp/offload")
        model.eval()
        tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
        tokenizer.pad_token = tokenizer.eos_token
        _model, _tokenizer = model, tokenizer
    
    messages = [{"role":"system","content":"You are a CloudOps infrastructure assistant. Output ONLY the JSON tool call. No explanations, no markdown."},{"role":"user","content":prompt}]
    import torch
    inputs = _tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_tensors="pt").to(_model.device)
    with torch.no_grad():
        outputs = _model.generate(inputs.input_ids, max_new_tokens=256, do_sample=False, pad_token_id=_tokenizer.eos_token_id)
    reply = _tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    try: return json.loads(reply)
    except: return {"error": "invalid JSON", "raw": reply}

# ── Safety check ───────────────────────────────────────────────────────
SAFETY = {
    "create_ec2_instance": {"allowed":{"region","instance_type","security_group_rules","tags"},"required":["region","instance_type"]},
    "restart_database": {"allowed":{"db_instance_identifier","region","force_failover"},"required":["db_instance_identifier","region"]},
    "get_billing_alert": {"allowed":{"time_period_start","time_period_end","granularity","metrics","group_by_service"},"required":[]},
}
PRICES = {"t3.nano":4,"t3.micro":8,"t3.small":15,"t3.medium":30,"m5.large":70,"m5.xlarge":140,"c6i.large":62,"r5.large":92}

def safety(name, args):
    warns = []
    s = SAFETY.get(name)
    if not s: return False, ["Unknown tool"]
    for k in args:
        if k not in s["allowed"]: warns.append(f"Unknown param '{k}' — blocked")
    for k in s["required"]:
        if k not in args: warns.append(f"Missing required: {k}")
    if name == "create_ec2_instance":
        cost = PRICES.get(args.get("instance_type",""), 20)
        warns.append(f"~${cost}/mo ({args.get('instance_type','t3.micro')})")
    return len([w for w in warns if "blocked" in w]) == 0, warns

# ── CLI ────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h","--help"):
        print("\n  ArcOps — NL → AWS tool calls\n")
        print("  arcops \"Create a t3.micro server\"    Generate tool call")
        print("  arcops --json \"...\"                  Raw JSON output")
        print("  arcops --real \"...\"                  Execute on real AWS")
        print("  arcops serve                          Start model server")
        print("\n  Examples:")
        print("  arcops \"Create a t3.micro server in us-east-1\"")
        print("  arcops \"How much did we spend this month?\"")
        print("  arcops --json \"Restart the production database\"")
        return

    if sys.argv[1] == "serve":
        print("* Model server mode not available from pip install.")
        print("* Use without 'serve' for one-shot inference.")
        return

    if sys.argv[1] in ("start","stop","dashboard","tui"):
        print("* Use 'arcops \"your prompt\"' directly (auto-loads model).")
        return

    if sys.argv[1] == "tools":
        print("\n  EC2 — Create a virtual server")
        print("  RDS — Restart a database")
        print("  Billing — Get cost and usage data\n")
        return

    # Parse args
    flags = {"--json","--real"}
    for f in flags:
        if f in sys.argv: os.environ.setdefault("ARC_OPS_REAL", "1" if f == "--real" else "")
    prompt = " ".join(a for a in sys.argv[1:] if a not in flags)

    # Generate
    result = infer(prompt)

    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False))
        return

    # Show result + safety
    name = result.get("name","")
    args = result.get("arguments",{})
    ok, warns = safety(name, args)
    
    print(f"\n  > {prompt}")
    print(f"  => {json.dumps(result, ensure_ascii=False)}")
    if warns:
        print(f"\n  {'-- Safety --'}")
        for w in warns: print(f"  {w}")
        if not ok: print(f"  Action BLOCKED")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print()
