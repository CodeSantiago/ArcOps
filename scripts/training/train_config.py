"""Pydantic configuration model for QLoRA fine-tuning pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError


class ModelConfig(BaseModel):
    """HuggingFace model loading configuration."""

    name: str = Field(..., min_length=1, description="HF model ID or path")
    load_in_4bit: bool = True
    bnb_4bit_quant_type: Literal["nf4", "fp4"] = "nf4"
    bnb_4bit_compute_dtype: str = "bf16"
    bnb_4bit_use_double_quant: bool = True


class LoraConfig(BaseModel):
    """LoRA adapter hyperparameters."""

    r: int = Field(default=16, gt=0, description="LoRA rank")
    lora_alpha: int = Field(default=32, gt=0, description="LoRA alpha scaling")
    target_modules: list[str] = Field(..., min_length=1, description="Modules to attach LoRA")
    lora_dropout: float = Field(default=0.1, ge=0.0, le=1.0, description="Dropout probability")
    bias: str = Field(
        default="none", pattern=r"^(none|all|lora_only)$", description="LoRA bias mode"
    )


class TrainingArgs(BaseModel):
    """Training hyperparameters and runtime configuration."""

    per_device_train_batch_size: int = Field(default=1, gt=0)
    per_device_eval_batch_size: int = Field(default=1, gt=0)
    gradient_accumulation_steps: int = Field(default=4, gt=0)
    gradient_checkpointing: bool = True
    learning_rate: float = Field(default=2e-4, gt=0.0)
    num_train_epochs: int = Field(default=3, gt=0)
    warmup_ratio: float = Field(default=0.03, ge=0.0, le=1.0)
    logging_steps: int = Field(default=5, gt=0)
    save_strategy: str = Field(
        default="epoch", pattern=r"^(steps|epoch|no)$"
    )
    eval_strategy: str = Field(
        default="epoch", pattern=r"^(steps|epoch|no)$"
    )
    save_steps: int | None = Field(
        default=None, ge=1, description="Used when save_strategy='steps'"
    )
    eval_steps: int | None = Field(
        default=None, ge=1, description="Used when eval_strategy='steps'"
    )
    save_total_limit: int = Field(default=3, ge=-1)
    optim: str = "adamw_8bit"
    bf16: bool = True
    max_grad_norm: float = Field(default=0.3, gt=0.0)
    lr_scheduler_type: str = "cosine"
    max_seq_length: int = Field(default=512, gt=0)
    output_dir: str = "./checkpoints"
    report_to: str = "none"


class DataConfig(BaseModel):
    """Dataset configuration."""

    train_file: str = Field(..., min_length=1, description="Path to training data JSONL")
    val_split: float = Field(default=0.2, ge=0.0, le=1.0, description="Validation split ratio")
    seed: int = Field(default=42, description="Random seed")


class TrainingConfig(BaseModel):
    """Top-level training configuration, composed of sub-configs."""

    model: ModelConfig
    lora: LoraConfig
    training: TrainingArgs
    data: DataConfig

    @classmethod
    def from_yaml(cls, path: Path) -> TrainingConfig:
        """Load TrainingConfig from a YAML file.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            A validated TrainingConfig instance.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            ValidationError: If the YAML content fails model validation.
            yaml.YAMLError: If the YAML is malformed.
        """
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path}")
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        try:
            return cls(**data)
        except TypeError as exc:
            # Wrap unexpected top-level keys as validation errors
            raise ValidationError.from_exception_data(
                title="TrainingConfig",
                line_errors=[{
                    "loc": ("_unknown",),
                    "msg": str(exc),
                    "type": "value_error.extra",
                }],
            ) from exc

    def to_yaml(self, path: Path) -> None:
        """Serialize this config to a YAML file.

        Args:
            path: Destination path for the YAML file.
        """
        data = self.model_dump(mode="python")
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
