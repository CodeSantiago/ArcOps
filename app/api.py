"""ArcOps API — NL → AWS JSON tool calls via FastAPI.

Run locally (binds to 127.0.0.1 by default):

    uvicorn api:app --host 127.0.0.1 --port 8080
    # or:  python -m app.api

The model stack (torch/transformers/peft) is imported lazily inside
``load()`` so the module itself imports without the ML extras installed.

Security defaults:

- Binds to localhost by default (override with --host when you know why).
- ``max_tokens`` is clamped to 1..1024.
- Optional API key: set ``ARC_OPS_API_KEY``; requests must then send the
  ``X-API-Key`` header. Without it the API is localhost-only by default.
- Every tool call is validated by the canonical safety module
  (``cloudops_fc.safety``); schema violations are rejected with HTTP 400.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cloudops_fc.models import resolve_model_config  # noqa: E402
from cloudops_fc.safety import check  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("arcops")

app = FastAPI(title="ArcOps", version="0.1.0", description="NL → JSON tool calls for AWS")

_OFFLOAD_DIR = os.getenv("ARC_OPS_OFFLOAD_DIR") or str(
    Path(tempfile.gettempdir()) / "arcops-offload"
)
_HERE = Path(__file__).resolve().parent

_model = None
_tokenizer = None

MAX_NEW_TOKENS_UPPER = 1024


class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    max_tokens: int = Field(default=256, ge=1, le=MAX_NEW_TOKENS_UPPER)


class ToolCallResponse(BaseModel):
    tool_call: dict
    raw: str
    safety: dict | None = None


def _require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce the optional API key when ARC_OPS_API_KEY is configured."""
    expected = os.environ.get("ARC_OPS_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _model_config() -> Any:
    """Resolve the model selection from ARC_OPS_MODEL/ARC_OPS_ADAPTER."""
    try:
        return resolve_model_config()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def load() -> tuple[Any, Any]:
    """Lazily load the 4-bit base model + LoRA adapter (singleton)."""
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Model inference requires the ML extras, which are not installed.\n"
            "Install them with:  pip install 'cloudops-fc[train]'"
        ) from exc

    cfg = _model_config()
    adapter = cfg.require_adapter()
    log.info("Loading base model %s (4-bit)...", cfg.name)
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        cfg.name, quantization_config=bnb, device_map="auto", torch_dtype=torch.bfloat16
    )
    log.info("Loading adapter from %s", adapter)
    model = PeftModel.from_pretrained(model, adapter, offload_folder=_OFFLOAD_DIR)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(cfg.name)
    tokenizer.pad_token = tokenizer.eos_token
    _model, _tokenizer = model, tokenizer
    log.info("Model ready")
    return model, tokenizer


@app.on_event("startup")
def startup() -> None:
    log.info("ArcOps loading model (this may take ~60s)...")
    try:
        load()
    except RuntimeError as exc:
        log.warning("Model not loaded at startup: %s", exc)
    log.info("ArcOps ready → http://localhost:8080/docs")


@app.get("/")
def index() -> Any:
    html = _HERE / "index.html"
    if html.exists():
        return HTMLResponse(html.read_text(encoding="utf-8"))
    return JSONResponse({"message": "ArcOps API — visit /docs for Swagger UI"})


@app.get("/health")
def health() -> dict[str, str]:
    try:
        cfg = _model_config()
        return {"status": "ok", "model": cfg.name, "adapter": cfg.adapter or ""}
    except (ValueError, RuntimeError) as exc:
        return {"status": "error", "detail": str(exc)}


def _predict(prompt: str, max_tokens: int) -> tuple[dict, str]:
    """Run inference and return (parsed tool call, raw reply)."""
    import torch

    model, tokenizer = load()
    messages = [
        {
            "role": "system",
            "content": (
                "You are a CloudOps infrastructure assistant. "
                "Output ONLY the JSON tool call. No explanations, no markdown."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    inputs = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
    ).to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            inputs.input_ids,
            max_new_tokens=max_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    raw = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
    ).strip()
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail=f"Model returned invalid JSON: {raw}"
        ) from exc


@app.post("/predict", response_model=ToolCallResponse)
def predict(
    req: PromptRequest, _: None = Depends(_require_api_key)
) -> ToolCallResponse:
    try:
        tool_call, raw = _predict(req.prompt, req.max_tokens)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    name = tool_call.get("name", "")
    arguments = tool_call.get("arguments", {})
    result = check(name, arguments)
    if result.blocked:
        raise HTTPException(
            status_code=400,
            detail={
                "tool_call": tool_call,
                "errors": result.errors,
            },
        )
    return ToolCallResponse(
        tool_call=tool_call, raw=raw, safety=result.to_dict()
    )


@app.post("/v1/chat/completions")
def openai_compat(
    req: dict, _: None = Depends(_require_api_key)
) -> dict[str, Any]:
    """OpenAI-compatible endpoint for MCP / opencode integration."""
    messages = req.get("messages") or [{}]
    prompt = messages[-1].get("content", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="No prompt provided")
    max_tokens = int(req.get("max_tokens") or 256)
    max_tokens = max(1, min(max_tokens, MAX_NEW_TOKENS_UPPER))
    try:
        tool_call, _raw = _predict(prompt, max_tokens)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    name = tool_call.get("name", "")
    arguments = tool_call.get("arguments", {})
    result = check(name, arguments)
    if result.blocked:
        raise HTTPException(
            status_code=400,
            detail={"tool_call": tool_call, "errors": result.errors},
        )
    return {
        "choices": [
            {"message": {"content": json.dumps(tool_call, ensure_ascii=False)}}
        ]
    }


if __name__ == "__main__":
    import uvicorn

    # Localhost by default — bind to 0.0.0.0 only inside the Docker image.
    uvicorn.run(app, host="127.0.0.1", port=8080)
