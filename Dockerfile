FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

WORKDIR /app

RUN pip install --no-cache-dir \
    transformers>=4.47 \
    peft>=0.14 \
    bitsandbytes>=0.45 \
    accelerate>=1.2 \
    huggingface_hub>=0.27 \
    fastapi uvicorn pydantic

COPY app/ /app/
COPY scripts/mcp_server.py /app/scripts/mcp_server.py

# The adapter is loaded from HuggingFace at runtime
ENV HF_HOME=/app/.cache
ENV ARC_OPS_ADAPTER=sayer1/arcops

EXPOSE 8080

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
