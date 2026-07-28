"""Tests for pyproject.toml train optional-dependencies group (RED phase)."""

from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TRAIN_DEPS: dict[str, str | None] = {
    "torch": ">=2.6",
    "transformers": ">=4.47",
    "datasets": ">=3.2",
    "peft": ">=0.14",
    "trl": ">=0.15",
    "bitsandbytes": ">=0.45",
    "accelerate": ">=1.2",
    "huggingface_hub": ">=0.27",
    "pydantic": None,
    "pyyaml": None,
}


class TestTrainDepsGroup:
    """R1: pyproject.toml MUST define a 'train' optional-dependencies group."""

    def _load_pyproject(self) -> dict:
        """Load pyproject.toml and return parsed data."""
        path = PROJECT_ROOT / "pyproject.toml"
        with path.open("rb") as f:
            return tomllib.load(f)

    def test_train_group_exists(self) -> None:
        """Given pyproject.toml, a [project.optional-dependencies] train group MUST exist."""
        data = self._load_pyproject()
        groups = data.get("project", {}).get("optional-dependencies", {})
        assert "train" in groups, (
            "Missing [project.optional-dependencies] train group"
        )

    def test_train_group_contains_all_expected_deps(self) -> None:
        """The train group MUST include every required ML dependency."""
        data = self._load_pyproject()
        deps: list[str] = data["project"]["optional-dependencies"]["train"]
        dep_names = {d.split(">=")[0].split("<")[0].split("!=")[0].strip() for d in deps}
        for name, constraint in EXPECTED_TRAIN_DEPS.items():
            assert name in dep_names, f"Missing dependency: {name}"
            matching = [d for d in deps if d.startswith(name)]
            if constraint and matching:
                assert constraint in matching[0], (
                    f"{name} constraint mismatch: expected {constraint}, got {matching[0]}"
                )

    def test_train_group_has_no_duplicate_entries(self) -> None:
        """Each package MUST appear at most once in the train group."""
        data = self._load_pyproject()
        deps: list[str] = data["project"]["optional-dependencies"]["train"]
        dep_names = [d.split(">=")[0].split("<")[0].strip() for d in deps]
        seen: set[str] = set()
        for name in dep_names:
            assert name not in seen, f"Duplicate dependency: {name}"
            seen.add(name)
