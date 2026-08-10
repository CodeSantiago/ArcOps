"""Tests for TRL SFTTrainer API compatibility in the training script.

These are lightweight static tests — they never load a model, download
weights, or run training. They guard against the regression where
``train.py`` passes the deprecated ``tokenizer`` kwarg to ``SFTTrainer``
instead of the supported ``processing_class`` kwarg (TRL >= 0.15).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRAIN_PY = PROJECT_ROOT / "scripts" / "training" / "train.py"


def _find_sft_trainer_calls() -> list[ast.Call]:
    """Return the SFTTrainer(...) call nodes in train.py, if any."""
    tree = ast.parse(TRAIN_PY.read_text(encoding="utf-8"))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "SFTTrainer":
                calls.append(node)
    return calls


class TestSFTTrainerKwargs:
    """train.py MUST construct SFTTrainer with the supported kwarg name."""

    def test_train_py_uses_processing_class(self) -> None:
        """The SFTTrainer(...) call MUST pass processing_class=, not tokenizer=."""
        calls = _find_sft_trainer_calls()
        assert calls, "train.py should construct an SFTTrainer"

        keyword_names = {kw.arg for call in calls for kw in call.keywords if kw.arg is not None}
        assert "processing_class" in keyword_names, (
            "SFTTrainer(...) must use the supported `processing_class` kwarg"
        )
        assert "tokenizer" not in keyword_names, (
            "SFTTrainer(...) must not use the deprecated `tokenizer` kwarg"
        )

    def test_train_py_preserves_pre_tokenized_inputs(self) -> None:
        """The pre-tokenized dataset path MUST remain intact.

        The dataset is tokenized with labels before the trainer is built,
        so the SFTTrainer call must pass the explicit data_collator and the
        tokenized train/val splits (no formatting_func re-tokenization).
        """
        calls = _find_sft_trainer_calls()
        call = calls[0]
        keyword_names = {kw.arg for kw in call.keywords if kw.arg is not None}
        assert "data_collator" in keyword_names
        assert "train_dataset" in keyword_names
        assert "eval_dataset" in keyword_names
        assert "formatting_func" not in keyword_names


class TestInstalledTRLApi:
    """The installed TRL must expose the API train.py now relies on."""

    def test_sft_trainer_accepts_processing_class(self) -> None:
        """If TRL is installed, its SFTTrainer signature MUST include processing_class."""
        trl = pytest.importorskip("trl")
        import inspect

        from trl import SFTTrainer

        params = inspect.signature(SFTTrainer.__init__).parameters
        assert "processing_class" in params, (
            f"Installed TRL {trl.__version__} lacks `processing_class` "
            "on SFTTrainer.__init__"
        )
        assert "tokenizer" not in params, (
            f"Installed TRL {trl.__version__} still exposes `tokenizer`; "
            "train.py uses the deprecated path"
        )
