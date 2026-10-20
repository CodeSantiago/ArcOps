"""ArcOps API — NL → AWS JSON tool calls via FastAPI.

Run locally (binds to 127.0.0.1 by default):

    pip install '.[api]'
    uvicorn app.api:app --host 127.0.0.1 --port 8080
    # or:  python -m app.api

Inference lives in ``cloudops_fc.core``; the ML stack is imported lazily so
the module itself imports without the ML extras installed.

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
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cloudops_fc.core import MAX_NEW_TOKENS, infer, load_model  # noqa: E402
from cloudops_fc.models import resolve_model_config  # noqa: E402
from cloudops_fc.safety import check  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("arcops")

MAX_NEW_TOKENS_UPPER = 1024
_HERE = Path(__file__).resolve().parent


class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    max_tokens: int = Field(default=MAX_NEW_TOKENS, ge=1, le=MAX_NEW_TOKENS_UPPER)


class ToolCallResponse(BaseModel):
    tool_call: dict[str, Any]
    raw: str
    safety: dict[str, Any] | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> Any:
    log.info("ArcOps loading model (this may take ~60s)...")
    try:
        load_model(resolve_model_config())
    except (RuntimeError, ValueError) as exc:
        log.warning("Model not loaded at startup: %s", exc)
    log.info("ArcOps ready → http://localhost:8080/docs")
    yield


app = FastAPI(
    title="ArcOps",
    version="0.1.0",
    description="NL → JSON tool calls for AWS",
    lifespan=lifespan,
)


def _require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce the optional API key when ARC_OPS_API_KEY is configured."""
    expected = os.environ.get("ARC_OPS_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _model_config() -> Any:
    """Resolve the model selection from ARC_OPS_MODEL/ARC_OPS_ADAPTER."""
    try:
        return resolve_model_config()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/")
def index() -> Any:
    html = _HERE / "index.html"
    if html.exists():
        return HTMLResponse(html.read_text(encoding="utf-8"))
    return JSONResponse({"message": "ArcOps API — visit /docs for Swagger UI"})


@app.get("/health")
def health() -> dict[str, str]:
    try:
        cfg = resolve_model_config()
        return {"status": "ok", "model": cfg.name, "adapter": cfg.adapter or ""}
    except (ValueError, RuntimeError) as exc:
        return {"status": "error", "detail": str(exc)}


def _predict(prompt: str, max_tokens: int) -> dict[str, Any]:
    """Run inference and return the parsed tool call."""
    cfg = _model_config()
    try:
        return infer(prompt, cfg, max_new_tokens=max_tokens)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _validated(tool_call: dict[str, Any]) -> dict[str, Any]:
    name = tool_call.get("name", "")
    arguments = tool_call.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}
    result = check(name, arguments)
    if result.blocked:
        raise HTTPException(
            status_code=400,
            detail={"tool_call": tool_call, "errors": result.errors},
        )
    return result.to_dict()


@app.post("/predict", response_model=ToolCallResponse)
def predict(req: PromptRequest, _: None = Depends(_require_api_key)) -> ToolCallResponse:
    tool_call = _predict(req.prompt, req.max_tokens)
    safety = _validated(tool_call)
    return ToolCallResponse(
        tool_call=tool_call,
        raw=json.dumps(tool_call, ensure_ascii=False),
        safety=safety,
    )


def _extract_prompt(messages: list[Any]) -> str:
    if not messages:
        return ""
    content = messages[-1].get("content", "") if isinstance(messages[-1], dict) else ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "".join(parts)
    return ""


@app.post("/v1/chat/completions")
def openai_compat(req: dict[str, Any], _: None = Depends(_require_api_key)) -> dict[str, Any]:
    """OpenAI-compatible endpoint for MCP / opencode integration."""
    prompt = _extract_prompt(req.get("messages") or [])
    if not prompt:
        raise HTTPException(status_code=400, detail="No prompt provided")

    try:
        max_tokens = int(req.get("max_tokens") or MAX_NEW_TOKENS)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="max_tokens must be an integer") from exc
    max_tokens = max(1, min(max_tokens, MAX_NEW_TOKENS_UPPER))

    tool_call = _predict(prompt, max_tokens)
    _validated(tool_call)
    cfg = resolve_model_config()
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": cfg.name,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(tool_call, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


if __name__ == "__main__":
    import uvicorn

    # Localhost by default — bind to 0.0.0.0 only inside the Docker image.
    uvicorn.run(app, host="127.0.0.1", port=8080)
