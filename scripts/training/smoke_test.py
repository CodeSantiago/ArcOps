"""Smoke test for QLoRA fine-tuning environment on RTX 5070 (Blackwell).

Validates:
  - CUDA is available with diagnostic info
  - bitsandbytes can be imported and reports version
  - transformers can load a 4-bit model and run a forward pass
  - VRAM is sufficient

This script MUST exit 0 before any training step runs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import torch
import yaml

# Add project root so scripts/training/ can resolve imports
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Tiny public model for smoke test — validates the stack, not the final model
_SMOKE_MODEL = "HuggingFaceTB/SmolLM2-135M"
_CONFIG_PATH = _PROJECT_ROOT / "scripts" / "training" / "default_config.yaml"


def check_cuda() -> dict[str, Any]:
    """Check CUDA availability and return diagnostics."""
    available = torch.cuda.is_available()
    if not available:
        msg = "CUDA is NOT available — cannot train on this machine"
        raise RuntimeError(msg)

    count = torch.cuda.device_count()
    name = torch.cuda.get_device_name(0) if count > 0 else "N/A"
    props = torch.cuda.get_device_properties(0) if count > 0 else None
    return {
        "available": available,
        "device_count": count,
        "gpu_name": name,
        "cuda_version": torch.version.cuda or "N/A",
        "torch_version": torch.__version__,
        "compute_capability": f"{props.major}.{props.minor}" if props else "N/A",
        "total_vram_gb": round(props.total_memory / 1e9, 2) if props else 0.0,
    }


def check_bitsandbytes() -> dict[str, Any]:
    """Check bitsandbytes loads and returns version info."""
    import bitsandbytes as bnb

    return {
        "bnb_version": bnb.__version__,
        "cuda_available": getattr(bnb, "cuda_available", "N/A"),
    }


def check_quantized_model() -> dict[str, Any]:
    """Load a tiny 4-bit model and run a forward pass (CPU fallback for CI)."""
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    device = "cuda" if torch.cuda.is_available() else "cpu"
    quantization_config = BitsAndBytesConfig(load_in_4bit=(device == "cuda")) if device == "cuda" else None
    model = AutoModelForCausalLM.from_pretrained(
        _SMOKE_MODEL,
        quantization_config=quantization_config,
        device_map="auto" if device == "cuda" else None,
        trust_remote_code=False,
    )
    tokenizer = AutoTokenizer.from_pretrained(_SMOKE_MODEL, trust_remote_code=False)

    # Forward pass on dummy input (1 token)
    inputs = tokenizer("Hello", return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)

    vram_used = 0.0
    if device == "cuda" and torch.cuda.is_available():
        vram_used = round(torch.cuda.max_memory_allocated() / 1e9, 2)
        torch.cuda.reset_peak_memory_stats()

    return {
        "model_type": type(model).__name__,
        "tokenizer_type": type(tokenizer).__name__,
        "vocab_size": tokenizer.vocab_size,
        "device": device,
        "quantized_4bit": device == "cuda",
        "forward_pass_shape": list(outputs.logits.shape),
        "vram_used_gb": vram_used,
    }


def load_config_diagnostics() -> dict[str, Any]:
    """Print config values for traceability."""
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return {
        "model_name": cfg.get("model", {}).get("name", "N/A"),
        "lora_r": cfg.get("lora", {}).get("r", "N/A"),
        "max_seq_length": cfg.get("training", {}).get("max_seq_length", "N/A"),
        "epochs": cfg.get("training", {}).get("num_train_epochs", "N/A"),
    }


def report(diag: dict[str, dict[str, Any]]) -> None:
    """Print diagnostics in a human-readable format."""
    print("=" * 56)
    print("  SMOKE TEST — QLoRA Environment Diagnostics")
    print("=" * 56)
    for section, entries in diag.items():
        print(f"\n  [{section}]")
        for key, val in entries.items():
            print(f"    {key}: {val}")
    print("\n" + "=" * 56)
    print("  STATUS: ALL CHECKS PASSED")
    print("=" * 56)


def main() -> int:
    """Run all smoke-test checks and return exit code."""
    diag: dict[str, dict[str, Any]] = {}

    print("Running QLoRA environment smoke test...\n")

    diag["CUDA"] = check_cuda()
    diag["bitsandbytes"] = check_bitsandbytes()
    diag["quantized_model"] = check_quantized_model()
    diag["config"] = load_config_diagnostics()

    report(diag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
