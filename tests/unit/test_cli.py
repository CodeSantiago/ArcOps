"""Tests for the arcops CLI (cloudops_fc.cli) without ML dependencies.

Covers the metadata commands that must work from a clean CPU-only install
(``--help``, ``tools``) and the failure path for ``--eval`` when the ML
extras are not installed (clear error, exit code 1).
"""

from __future__ import annotations

from cloudops_fc import cli, core


class TestCliMetadata:
    """Metadata commands MUST work without the ML stack."""

    def test_no_args_prints_help(self, capsys) -> None:
        code = cli.main([])
        out = capsys.readouterr().out
        assert code == 0
        assert "ArcOps" in out
        assert "--eval" in out

    def test_help_flag(self, capsys) -> None:
        code = cli.main(["--help"])
        assert code == 0
        assert "ArcOps" in capsys.readouterr().out

    def test_tools_subcommand(self, capsys) -> None:
        code = cli.main(["tools"])
        out = capsys.readouterr().out
        assert code == 0
        assert "EC2" in out
        assert "RDS" in out
        assert "Billing" in out

    def test_unknown_model_key_fails_clearly(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("ARC_OPS_MODEL", "13b")
        code = cli.main(["create a server"])
        out = capsys.readouterr().out
        assert code == 2
        assert "Unknown ARC_OPS_MODEL" in out

    def test_eval_without_ml_extra_fails_gracefully(self, capsys, monkeypatch) -> None:
        """--eval MUST report a clear error when the runtime cannot load."""

        def _no_runtime(*_args, **_kwargs):
            raise RuntimeError(
                "Model inference requires the ML extras, which are not installed.\n"
                "Install them with:  pip install 'cloudops-fc[train]'"
            )

        # The lazy ML runtime now lives in the shared engine (cloudops_fc.core).
        monkeypatch.setattr(core, "_load_runtime", _no_runtime)
        code = cli.main(["--eval"])
        out = capsys.readouterr().out
        assert code == 1
        assert "ML extras" in out
