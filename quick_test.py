"""Quick test: raw model output"""
import json, torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-7B-Instruct", quantization_config=bnb_config, device_map="auto", torch_dtype=torch.bfloat16)
model = PeftModel.from_pretrained(model, "checkpoints/final", offload_folder="offload")
model.eval()
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
tokenizer.pad_token = tokenizer.eos_token

messages = [{"role":"system","content":"Eres un asistente de infraestructura cloud. Debes responder ÚNICAMENTE con tool calls en formato JSON."},
            {"role":"user","content":"Creame un server t3.micro en us-east-1 con puerto 80"}]
inputs = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_tensors="pt").to(model.device)
outputs = model.generate(inputs.input_ids, max_new_tokens=128, do_sample=False, pad_token_id=tokenizer.eos_token_id)
reply = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
print("RAW:", reply)
print("---")
try:
    parsed = json.loads(reply)
    print("OK:", json.dumps(parsed, ensure_ascii=False))
except:
    print("FAIL: not valid JSON")
