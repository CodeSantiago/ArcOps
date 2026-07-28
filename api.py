"""ArcOps API — NL → AWS JSON tool calls via FastAPI."""
import json, logging, os
from pathlib import Path
from typing import Optional

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from app.safety import check as safety_check

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("arcops")

app = FastAPI(title="ArcOps", version="0.1.0", description="NL → JSON tool calls for AWS")

ADAPTER = os.getenv("ARC_OPS_ADAPTER", "sayer1/arcops")
MODEL = "Qwen/Qwen2.5-7B-Instruct"

_model = None
_tokenizer = None
_HERE = Path(__file__).resolve().parent


class PromptRequest(BaseModel):
    prompt: str
    max_tokens: Optional[int] = 256


class ToolCallResponse(BaseModel):
    tool_call: dict
    raw: str


def load():
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    log.info("Loading base model (4-bit)...")
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=bnb, device_map="auto", torch_dtype=torch.bfloat16)
    log.info("Loading adapter from %s", ADAPTER)
    model = PeftModel.from_pretrained(model, ADAPTER, offload_folder="/tmp/offload")
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(MODEL)
    tokenizer.pad_token = tokenizer.eos_token
    _model, _tokenizer = model, tokenizer
    log.info("Model ready")
    return model, tokenizer


@app.on_event("startup")
def startup():
    log.info("ArcOps loading model (this may take ~60s)...")
    load()
    log.info("ArcOps ready → http://localhost:8080/docs")


@app.get("/")
def index():
    html = _HERE / "index.html"
    if html.exists():
        return HTMLResponse(html.read_text())
    return JSONResponse({"message": "ArcOps API — visit /docs for Swagger UI"})


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL, "adapter": ADAPTER}


@app.post("/predict", response_model=ToolCallResponse)
def predict(req: PromptRequest):
    model, tokenizer = load()
    messages = [
        {"role": "system", "content": "You are a CloudOps infrastructure assistant. Output ONLY the JSON tool call. No explanations, no markdown."},
        {"role": "user", "content": req.prompt},
    ]
    inputs = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(inputs.input_ids, max_new_tokens=req.max_tokens, do_sample=False, pad_token_id=tokenizer.eos_token_id)
    raw = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    try:
        tool_call = json.loads(raw)
        return ToolCallResponse(tool_call=tool_call, raw=raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Model returned invalid JSON: {raw}")


@app.post("/predict/safe")
def predict_safe(req: PromptRequest):
    """Predict + safety check. Returns tool call + safety results."""
    result = predict(req)
    tc = result.tool_call
    sr = safety_check(tc.get("name", ""), tc.get("arguments", {}))
    return {
        "tool_call": tc,
        "raw": result.raw,
        "safety": sr.to_dict(),
    }


@app.post("/v1/chat/completions")
def openai_compat(req: dict):
    """OpenAI-compatible endpoint for MCP / opencode integration."""
    prompt = req.get("messages", [{}])[-1].get("content", "")
    result = predict(PromptRequest(prompt=prompt))
    return {
        "choices": [{"message": {"content": json.dumps(result.tool_call, ensure_ascii=False)}}]
    }
