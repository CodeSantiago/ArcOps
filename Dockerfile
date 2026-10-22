FROM pytorch/pytorch:2.14.1-cuda13.0-cudnn9-runtime

WORKDIR /app

RUN pip install --no-cache-dir \
    "transformers>=4.47,<6" \
    "peft>=0.14,<1" \
    "bitsandbytes>=0.45,<1" \
    "accelerate>=1.2,<2" \
    "huggingface_hub>=0.27,<2" \
    "fastapi>=0.115,<1" \
    "uvicorn>=0.32,<1" \
    "jsonschema>=4.23,<5" \
    "pydantic>=2,<3" \
    "pyyaml>=6,<7"

COPY app/ /app/app/
COPY src/ /app/src/

ENV HF_HOME=/app/.cache
ENV ARC_OPS_MODEL=7b
ENV PYTHONPATH=/app/src

EXPOSE 8080

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8080"]
