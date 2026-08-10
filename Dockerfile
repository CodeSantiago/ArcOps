FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

WORKDIR /app

# All pip constraints are quoted so the shell never splits them.
RUN pip install --no-cache-dir \
    "transformers>=4.47" \
    "peft>=0.14" \
    "bitsandbytes>=0.45" \
    "accelerate>=1.2" \
    "huggingface_hub>=0.27" \
    "fastapi" "uvicorn" "pydantic"

COPY app/ /app/
COPY src/ /app/src/
COPY scripts/mcp_server.py /app/scripts/mcp_server.py

# The adapter is loaded from HuggingFace at runtime.
ENV HF_HOME=/app/.cache
ENV ARC_OPS_ADAPTER=CodeSantiago/arcops
ENV PYTHONPATH=/app/src

EXPOSE 8080

# Binds 0.0.0.0 because Docker containers have an isolated network and port
# publishing requires it; local (non-Docker) runs default to 127.0.0.1.
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
