"""Tests for unified model selection (cloudops_fc.models).

Requirement: ``ARC_OPS_MODEL=7b|1.5b`` must resolve consistently everywhere,
adapter defaults must use the real public repo (``CodeSantiago/arcops``),
and the 1.5B path must fail clearly instead of inventing a repo that does
not exist.
"""

from __future__ import annotations

import pytest

from cloudops_fc.models import (
    DEFAULT_ADAPTER,
    resolve_model_config,
)


class TestResolveModelConfig:
    """resolve_model_config MUST map keys to base model + adapter."""

    def test_default_is_7b_with_public_adapter(self) -> None:
        cfg = resolve_model_config(env={})
        assert cfg.key == "7b"
        assert cfg.name == "Qwen/Qwen2.5-7B-Instruct"
        assert cfg.adapter == DEFAULT_ADAPTER

    def test_7b_from_env(self) -> None:
        cfg = resolve_model_config(env={"ARC_OPS_MODEL": "7b"})
        assert cfg.key == "7b"
        assert cfg.adapter == "CodeSantiago/arcops"

    def test_env_adapter_override_wins(self) -> None:
        cfg = resolve_model_config(
            env={"ARC_OPS_ADAPTER": "me/my-adapter", "ARC_OPS_MODEL": "7b"}
        )
        assert cfg.adapter == "me/my-adapter"

    def test_1_5b_without_adapter_fails_clearly(self) -> None:
        with pytest.raises(RuntimeError, match="ARC_OPS_ADAPTER"):
            resolve_model_config(key="1.5b", env={})

    def test_1_5b_with_adapter_resolves(self) -> None:
        cfg = resolve_model_config(key="1.5b", adapter_override="me/my-1.5b")
        assert cfg.key == "1.5b"
        assert cfg.name == "Qwen/Qwen2.5-1.5B-Instruct"
        assert cfg.adapter == "me/my-1.5b"
        assert cfg.require_adapter() == "me/my-1.5b"

    def test_unknown_key_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown ARC_OPS_MODEL"):
            resolve_model_config(key="13b", env={})

    def test_key_case_insensitive(self) -> None:
        cfg = resolve_model_config(key="7B", env={})
        assert cfg.key == "7b"


class TestRequireAdapter:
    """require_adapter MUST surface a clear error when no adapter exists."""

    def test_require_adapter_success(self) -> None:
        cfg = resolve_model_config(env={})
        assert cfg.require_adapter() == DEFAULT_ADAPTER

    def test_require_adapter_failure_message(self) -> None:
        """require_adapter MUST be a defensive backstop for None adapters."""
        from cloudops_fc.models import ModelConfig

        cfg = ModelConfig(key="1.5b", name="Qwen/Qwen2.5-1.5B-Instruct", adapter=None)
        with pytest.raises(RuntimeError) as exc:
            cfg.require_adapter()
        assert "No public adapter exists" in str(exc.value)
        assert "ARC_OPS_ADAPTER" in str(exc.value)
