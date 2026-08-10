"""Tests for TrainingConfig Pydantic model (RED phase)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from scripts.training.train_config import (
    DataConfig,
    LoraConfig,
    ModelConfig,
    TrainingArgs,
    TrainingConfig,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "scripts" / "training" / "default_config.yaml"
INVALID_CONFIG_PATH = PROJECT_ROOT / "scripts" / "training" / "_invalid_test.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_tmp_yaml(data: dict) -> Path:
    """Write a temporary YAML file and return its path."""
    fd, path_str = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)  # release handle immediately
    tmp = Path(path_str)
    with tmp.open("w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return tmp


# ---------------------------------------------------------------------------
# ModelConfig
# ---------------------------------------------------------------------------

class TestModelConfig:
    """ModelConfig validation."""

    def test_defaults(self) -> None:
        """ModelConfig with only name sets expected defaults."""
        cfg = ModelConfig(name="test/model")
        assert cfg.load_in_4bit is True
        assert cfg.bnb_4bit_quant_type == "nf4"
        assert cfg.bnb_4bit_compute_dtype == "bf16"
        assert cfg.bnb_4bit_use_double_quant is True

    def test_rejects_empty_name(self) -> None:
        """ModelConfig with empty name MUST raise ValidationError."""
        with pytest.raises(Exception, match="name"):
            ModelConfig(name="")

    def test_rejects_invalid_quant_type(self) -> None:
        """bnb_4bit_quant_type MUST be nf4 or fp4."""
        with pytest.raises(Exception, match="nf4|fp4"):
            ModelConfig(name="test/model", bnb_4bit_quant_type="int8")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# LoraConfig
# ---------------------------------------------------------------------------

class TestLoraConfig:
    """LoraConfig validation."""

    def test_defaults(self) -> None:
        """LoraConfig with target_modules sets expected defaults."""
        cfg = LoraConfig(target_modules=["q_proj", "v_proj"])
        assert cfg.r == 16
        assert cfg.lora_alpha == 32
        assert cfg.lora_dropout == 0.1
        assert cfg.bias == "none"

    def test_rejects_zero_r(self) -> None:
        """r=0 MUST raise ValidationError."""
        with pytest.raises(Exception, match="r"):
            LoraConfig(r=0, lora_alpha=32, target_modules=["q_proj"])

    def test_rejects_negative_alpha(self) -> None:
        """negative lora_alpha MUST raise ValidationError."""
        with pytest.raises(Exception, match="lora_alpha"):
            LoraConfig(r=8, lora_alpha=-1, target_modules=["q_proj"])

    def test_rejects_empty_target_modules(self) -> None:
        """Empty target_modules MUST raise ValidationError."""
        with pytest.raises(Exception):
            LoraConfig(r=8, lora_alpha=32, target_modules=[])


# ---------------------------------------------------------------------------
# TrainingArgs
# ---------------------------------------------------------------------------

class TestTrainingArgs:
    """TrainingArgs validation."""

    def test_defaults(self) -> None:
        """TrainingArgs with no overrides sets expected defaults."""
        cfg = TrainingArgs()
        assert cfg.per_device_train_batch_size == 1
        assert cfg.gradient_accumulation_steps == 4
        assert cfg.learning_rate == 2e-4
        assert cfg.num_train_epochs == 3
        assert cfg.warmup_ratio == 0.03
        assert cfg.bf16 is True
        assert cfg.max_seq_length == 512
        assert cfg.output_dir == "./checkpoints"
        assert cfg.save_strategy == "epoch"
        assert cfg.eval_strategy == "epoch"

    def test_rejects_zero_batch_size(self) -> None:
        """batch_size=0 MUST raise ValidationError."""
        with pytest.raises(Exception):
            TrainingArgs(per_device_train_batch_size=0)

    def test_rejects_negative_lr(self) -> None:
        """negative learning_rate MUST raise ValidationError."""
        with pytest.raises(Exception):
            TrainingArgs(learning_rate=-1.0)

    def test_rejects_zero_epochs(self) -> None:
        """num_train_epochs=0 MUST raise ValidationError."""
        with pytest.raises(Exception):
            TrainingArgs(num_train_epochs=0)


# ---------------------------------------------------------------------------
# DataConfig
# ---------------------------------------------------------------------------

class TestDataConfig:
    """DataConfig validation."""

    def test_defaults(self) -> None:
        """DataConfig with only train_file sets expected defaults."""
        cfg = DataConfig(train_file="data.jsonl")
        assert cfg.val_split == 0.2
        assert cfg.seed == 42

    def test_rejects_val_split_out_of_range(self) -> None:
        """val_split outside [0, 1] MUST raise ValidationError."""
        with pytest.raises(Exception):
            DataConfig(train_file="data.jsonl", val_split=1.5)

    def test_zero_val_split_allowed(self) -> None:
        """val_split=0 is allowed (no validation set)."""
        cfg = DataConfig(train_file="data.jsonl", val_split=0.0)
        assert cfg.val_split == 0.0


# ---------------------------------------------------------------------------
# TrainingConfig (integration)
# ---------------------------------------------------------------------------

class TestTrainingConfigFromYaml:
    """TrainingConfig.from_yaml MUST load and validate YAML config files."""

    def test_from_yaml_loads_default_config(self) -> None:
        """Given default_config.yaml, from_yaml returns valid TrainingConfig."""
        config = TrainingConfig.from_yaml(DEFAULT_CONFIG_PATH)
        assert config.model.name == "Qwen/Qwen2.5-7B-Instruct"
        assert config.model.load_in_4bit is True
        assert config.lora.r == 32
        assert config.lora.lora_alpha == 64
        assert config.training.per_device_train_batch_size == 1
        assert config.training.gradient_accumulation_steps == 4
        assert config.training.learning_rate == 1e-4
        assert config.training.num_train_epochs == 6
        assert config.training.warmup_ratio == 0.03
        assert config.training.save_strategy == "epoch"
        assert config.training.eval_strategy == "epoch"
        assert config.training.bf16 is True
        assert config.training.max_seq_length == 512
        assert config.training.output_dir == "./checkpoints"
        assert config.data.train_file == "data/training_dataset.jsonl"
        assert config.data.val_split == 0.2
        assert config.data.seed == 42

    def test_to_yaml_round_trip(self) -> None:
        """to_yaml then from_yaml MUST produce identical config."""
        original = TrainingConfig.from_yaml(DEFAULT_CONFIG_PATH)
        fd, path_str = tempfile.mkstemp(suffix=".yaml")
        os.close(fd)
        tmp = Path(path_str)
        try:
            original.to_yaml(tmp)
            reloaded = TrainingConfig.from_yaml(tmp)
            assert reloaded.model.name == original.model.name
            assert reloaded.lora.r == original.lora.r
            assert reloaded.training.learning_rate == original.training.learning_rate
            assert reloaded.data.seed == original.data.seed
        finally:
            tmp.unlink(missing_ok=True)

    def test_from_yaml_rejects_missing_file(self) -> None:
        """from_yaml with nonexistent path MUST raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            TrainingConfig.from_yaml(Path("/nonexistent/config.yaml"))

    def test_from_yaml_rejects_invalid_yaml(self) -> None:
        """from_yaml with malformed YAML MUST raise a parsing error."""
        fd, path_str = tempfile.mkstemp(suffix=".yaml")
        os.close(fd)
        tmp = Path(path_str)
        try:
            tmp.write_text("{{{broken: yaml", encoding="utf-8")
            with pytest.raises(Exception):
                TrainingConfig.from_yaml(tmp)
        finally:
            tmp.unlink(missing_ok=True)


class TestTrainingConfigDirectConstruction:
    """TrainingConfig can be constructed directly from dicts."""

    def test_construct_full_config(self) -> None:
        """Given valid sub-configs, TrainingConfig() succeeds."""
        cfg = TrainingConfig(
            model=ModelConfig(name="test/model"),
            lora=LoraConfig(target_modules=["q_proj", "v_proj"]),
            training=TrainingArgs(),
            data=DataConfig(train_file="data.jsonl"),
        )
        assert cfg.model.name == "test/model"
        assert cfg.training.num_train_epochs == 3

    def test_construct_rejects_missing_model_name(self) -> None:
        """TrainingConfig with empty model name MUST raise."""
        with pytest.raises(Exception):
            TrainingConfig(
                model=ModelConfig(name=""),
                lora=LoraConfig(target_modules=["q_proj"]),
                training=TrainingArgs(),
                data=DataConfig(train_file="data.jsonl"),
            )
