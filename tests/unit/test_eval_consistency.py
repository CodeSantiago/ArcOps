"""Regression tests for the evaluation split-consistency gate.

The gate must compare against the *effective* evaluation seed (the one
recorded in the split metadata), not the raw ``--seed`` CLI value. Before
this fix, a standard evaluation of a fresh checkpoint always raised
"Seed mismatch" because ``args.seed`` defaults to ``None``.
"""

from __future__ import annotations

import argparse

import pytest

from scripts.training.eval import parse_args, verify_split_consistency


def _standard_args() -> argparse.Namespace:
    return parse_args(["--checkpoint", "checkpoints/final"])


class TestStandardMode:
    def test_training_metadata_with_config_seed_does_not_raise(self) -> None:
        args = _standard_args()
        training = {"mode": "standard", "split_seed": 42}
        evaluation = {"mode": "standard", "split_seed": 42}
        verify_split_consistency(training, args, evaluation)

    def test_effective_seed_mismatch_raises(self) -> None:
        args = _standard_args()
        training = {"mode": "standard", "split_seed": 42}
        evaluation = {"mode": "standard", "split_seed": 999}
        with pytest.raises(ValueError, match="Seed mismatch"):
            verify_split_consistency(training, args, evaluation)

    def test_mode_mismatch_raises(self) -> None:
        args = _standard_args()
        training = {"mode": "template", "split_seed": 42}
        evaluation = {"mode": "standard", "split_seed": 42}
        with pytest.raises(ValueError, match="mode"):
            verify_split_consistency(training, args, evaluation)


class TestTemplateMode:
    def test_matching_families_and_seed_pass(self) -> None:
        args = parse_args([
            "--checkpoint", "checkpoints/final",
            "--eval-mode", "template",
            "--test-families", "ec2_ports,rds_failover",
        ])
        training = {
            "mode": "template",
            "split_seed": 42,
            "test_families": ["ec2_ports", "rds_failover"],
        }
        evaluation = {
            "mode": "template",
            "split_seed": 42,
            "test_families": ["ec2_ports", "rds_failover"],
        }
        verify_split_consistency(training, args, evaluation)

    def test_family_mismatch_raises(self) -> None:
        args = parse_args([
            "--checkpoint", "checkpoints/final",
            "--eval-mode", "template",
            "--test-families", "ec2_ports",
        ])
        training = {
            "mode": "template",
            "split_seed": 42,
            "test_families": ["rds_failover"],
        }
        evaluation = {
            "mode": "template",
            "split_seed": 42,
            "test_families": ["ec2_ports"],
        }
        with pytest.raises(ValueError, match="families mismatch"):
            verify_split_consistency(training, args, evaluation)


class TestUnseenMode:
    def test_matching_values_pass(self) -> None:
        args = parse_args([
            "--checkpoint", "checkpoints/final",
            "--eval-mode", "unseen",
            "--unseen", "region=ca-central-1",
        ])
        training = {
            "mode": "unseen",
            "split_seed": 42,
            "unseen_values": {"region": ["ca-central-1"]},
        }
        evaluation = {
            "mode": "unseen",
            "split_seed": 42,
            "unseen_values": {"region": ["ca-central-1"]},
        }
        verify_split_consistency(training, args, evaluation)

    def test_value_mismatch_raises(self) -> None:
        args = parse_args([
            "--checkpoint", "checkpoints/final",
            "--eval-mode", "unseen",
            "--unseen", "region=ca-central-1",
        ])
        training = {
            "mode": "unseen",
            "split_seed": 42,
            "unseen_values": {"region": ["ap-northeast-1"]},
        }
        evaluation = {
            "mode": "unseen",
            "split_seed": 42,
            "unseen_values": {"region": ["ca-central-1"]},
        }
        with pytest.raises(ValueError, match="Unseen values mismatch"):
            verify_split_consistency(training, args, evaluation)
