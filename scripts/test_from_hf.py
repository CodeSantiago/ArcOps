"""Test ArcOps adapter from HuggingFace"""
import json, torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

MODEL = "Qwen/Qwen2.5-7B-Instruct"
ADAPTER = "sayer1/arcops"  # ← desde HuggingFace!

bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
model = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=bnb_config, device_map="auto", torch_dtype=torch.bfloat16)
model = PeftModel.from_pretrained(model, ADAPTER, offload_folder="offload")
model.eval()
tokenizer = AutoTokenizer.from_pretrained(MODEL)
tokenizer.pad_token = tokenizer.eos_token

tests = [
    "Creame un server t3.micro en us-east-1 con puerto 80",
    "Restart the production database",
    "Cuánto gastamos este mes",
]
for prompt in tests:
    messages = [{"role":"system","content":"Eres un asistente de infraestructura cloud. Debes responder ÚNICAMENTE con tool calls en formato JSON."},
                {"role":"user","content":prompt}]
    inputs = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(inputs.input_ids, max_new_tokens=256, do_sample=False, pad_token_id=tokenizer.eos_token_id)
    reply = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    print(f"📝 {prompt}")
    print(f"🤖 {reply}\n")
