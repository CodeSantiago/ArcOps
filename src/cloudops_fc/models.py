"""Unified model selection for ArcOps.

Single source of truth for resolving ``ARC_OPS_MODEL`` (``7b`` | ``1.5b``)
into a HuggingFace base model ID and an adapter repo ID, so the CLI, API,
MCP server, Docker image, and docs all agree.

Adapter defaults: only adapters known to exist publicly get a default
(``CodeSantiago/arcops`` for the 7B model). There is no public 1.5B adapter
yet, so selecting ``1.5b`` requires an explicit ``ARC_OPS_ADAPTER`` override
and fails with a clear error otherwise — the project never invents a repo ID
that does not exist.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL_KEY = "7b"
DEFAULT_ADAPTER = "CodeSantiago/arcops"

#: Base model ID per model key. ``adapter`` is the default adapter repo ID,
#: or ``None`` when no public adapter exists for that key.
_MODEL_REGISTRY: dict[str, dict[str, str | None]] = {
    "7b": {
        "name": "Qwen/Qwen2.5-7B-Instruct",
        "adapter": DEFAULT_ADAPTER,
    },
    "1.5b": {
        # Verified 2026-08: no public adapter exists at this key. Users must
        # supply their own via ARC_OPS_ADAPTER (see resolve_model_config).
        "name": "Qwen/Qwen2.5-1.5B-Instruct",
        "adapter": None,
    },
}

SUPPORTED_KEYS = tuple(sorted(_MODEL_REGISTRY))


@dataclass(frozen=True)
class ModelConfig:
    """A resolved model selection."""

    key: str
    name: str
    adapter: str | None

    def require_adapter(self) -> str:
        """Return the adapter repo ID or raise a clear RuntimeError."""
        if not self.adapter:
            raise RuntimeError(
                f"No public adapter exists for model '{self.key}' "
                f"(base model: {self.name}). Set ARC_OPS_ADAPTER to the "
                "HuggingFace repo ID of your fine-tuned LoRA adapter to use "
                "this model."
            )
        return self.adapter


def resolve_model_config(
    key: str | None = None,
    adapter_override: str | None = None,
    env: dict[str, str] | None = None,
) -> ModelConfig:
    """Resolve the effective model config from env vars and overrides.

    Args:
        key: Model key (``7b`` or ``1.5b``). Defaults to ``ARC_OPS_MODEL``.
        adapter_override: Explicit adapter repo ID. Defaults to
            ``ARC_OPS_ADAPTER``, then to the per-key default.
        env: Environment mapping (defaults to ``os.environ``).

    Raises:
        ValueError: Unknown model key.
        RuntimeError: ``1.5b`` selected without an explicit adapter override.
    """
    env = env if env is not None else os.environ
    key = str(key or env.get("ARC_OPS_MODEL", DEFAULT_MODEL_KEY)).strip().lower()
    if key not in _MODEL_REGISTRY:
        raise ValueError(
            f"Unknown ARC_OPS_MODEL '{key}'. Supported values: "
            f"{', '.join(SUPPORTED_KEYS)}."
        )
    adapter = adapter_override or env.get("ARC_OPS_ADAPTER")
    if adapter is None:
        adapter = _MODEL_REGISTRY[key]["adapter"]
    if adapter is None:
        # No public adapter exists for this key and none was provided.
        raise RuntimeError(
            f"No public adapter exists for model '{key}' "
            f"(base model: {_MODEL_REGISTRY[key]['name']}). Set "
            "ARC_OPS_ADAPTER to the HuggingFace repo ID of your fine-tuned "
            "LoRA adapter to use this model."
        )
    return ModelConfig(key=key, name=_MODEL_REGISTRY[key]["name"], adapter=adapter)


def model_name(key: str | None = None, env: dict[str, str] | None = None) -> str:
    """Return the base model ID for a model key."""
    return resolve_model_config(key=key, env=env).name
