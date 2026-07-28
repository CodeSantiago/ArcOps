"""Test different system prompts with the fine-tuned model."""
import json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"
ADAPTER_PATH = "checkpoints/final"

bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, quantization_config=bnb_config, device_map="auto", torch_dtype=torch.bfloat16)
model = PeftModel.from_pretrained(model, ADAPTER_PATH, offload_folder="offload")
model.eval()
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
tokenizer.pad_token = tokenizer.eos_token

tests = [
    "Cremá un server t3.medium en us-east-1 con el puerto 443 abierto",
    "Reiniciá la DB de producción que se colgó",
    "Cuánto gastamos este mes en AWS",
    "Dame un servidor en Virginia con 16GB de RAM",
    "Necesito un server grande en Oregon con tags Name=web, Env=prod",
]

prompts = [
    # Prompt original (baseline)
    "Eres un asistente de infraestructura cloud. Debes responder ÚNICAMENTE con tool calls en formato JSON.",
    
    # Prompt más específico sobre el formato
    "Eres un asistente cloud. Responde ÚNICAMENTE con JSON exacto: {\"name\": \"<TOOL>\", \"arguments\": {<PARAMS>}}. Sin explicaciones, sin markdown, solo JSON.",
    
    # Few-shot en el prompt
    "Eres un asistente cloud. Responde SOLO con JSON tool calls.\n\nEjemplos:\nUsuario: Cremá un server t3.micro en us-east-1\nAssistant: {\"name\": \"create_ec2_instance\", \"arguments\": {\"region\": \"us-east-1\", \"instance_type\": \"t3.micro\"}}\n\nUsuario: Cuánto gastamos\nAssistant: {\"name\": \"get_billing_alert\", \"arguments\": {}}\n\nAhora respondé:",
    
    # Prompt en inglés (el modelo base fue entrenado mayormente en inglés)
    "You are a CloudOps assistant. Output ONLY the JSON tool call. No explanations, no markdown.",
    
    # Prompt ultra estricto
    "Regla ABSOLUTA: Tu respuesta debe ser ÚNICAMENTE un objeto JSON de una línea. No uses markdown, no expliques, no saludes. Ejemplo válido: {\"name\":\"create_ec2_instance\",\"arguments\":{\"region\":\"us-east-1\"}}",
]

for prompt_template in prompts:
    print(f"\n{'='*60}")
    print(f"SYSTEM PROMPT: {prompt_template[:70]}...")
    print(f"{'='*60}")
    
    for test in tests:
        messages = [
            {"role": "system", "content": prompt_template},
            {"role": "user", "content": test},
        ]
        inputs = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_tensors="pt").to(model.device)
        with torch.no_grad():
            outputs = model.generate(inputs.input_ids, max_new_tokens=128, do_sample=False, pad_token_id=tokenizer.eos_token_id)
        reply = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        print(f"  📝 {test[:40]:40s} → {reply[:80]}")
