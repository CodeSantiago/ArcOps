"""Tests for the arcops CLI (cloudops_fc.cli) without ML dependencies.

Covers the metadata commands that must work from a clean CPU-only install
(``--help``, ``tools``) and the failure path for ``--eval`` when the ML
extras are not installed (clear error, exit code 1).
"""

from __future__ import annotations

import json
import sys
import types

from cloudops_fc import cli


class TestCliMetadata:
    """Metadata commands MUST work without the ML stack."""

    def test_no_args_prints_help(self, capsys) -> None:
        code = cli.main([])
        out = capsys.readouterr().out
        assert code == 0
        assert "ArcOps" in out
        assert "--eval" in out
        assert "tui" in out

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

        monkeypatch.setattr(cli, "infer", _no_runtime)
        code = cli.main(["--eval"])
        out = capsys.readouterr().out
        assert code == 1
        assert "ML extras" in out


class TestCliPrompt:
    """The prompt path MUST render safety decisions without an ML runtime."""

    def test_prompt_reports_approval_for_disruptive_action(
        self, capsys, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            cli,
            "infer",
            lambda prompt, cfg: {
                "name": "restart_database",
                "arguments": {
                    "db_instance_identifier": "prod-db",
                    "region": "us-east-1",
                },
            },
        )
        code = cli.main(["Restart the production database in us-east-1"])
        out = capsys.readouterr().out
        assert code == 0
        assert "Approval required before execution" in out
        assert "will cause downtime" in out

    def test_prompt_json_output(self, capsys, monkeypatch) -> None:
        call = {
            "name": "create_ec2_instance",
            "arguments": {"instance_type": "t3.micro", "region": "us-east-1"},
        }
        monkeypatch.setattr(cli, "infer", lambda prompt, cfg: call)
        code = cli.main(["--json", "Create a t3.micro server in us-east-1"])
        out = capsys.readouterr().out
        assert code == 0
        assert json.loads(out) == call

    def test_prompt_blocks_unknown_tool(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr(
            cli, "infer", lambda prompt, cfg: {"name": "delete_all", "arguments": {}}
        )
        code = cli.main(["delete everything"])
        out = capsys.readouterr().out
        assert code == 0
        assert "Action BLOCKED" in out
        assert "Unknown tool" in out

    def test_prompt_without_text_fails(self, capsys) -> None:
        code = cli.main(["--json"])
        out = capsys.readouterr().out
        assert code == 2
        assert "no prompt provided" in out

    def test_prompt_inference_runtime_error(self, capsys, monkeypatch) -> None:
        def _fail(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(cli, "infer", _fail)
        code = cli.main(["create a server"])
        out = capsys.readouterr().out
        assert code == 1
        assert "Error: boom" in out

    def test_tui_subcommand_dispatches_lazily(self, monkeypatch) -> None:
        fake = types.ModuleType("cloudops_fc.tui")
        calls: list[bool] = []
        fake.main = lambda: calls.append(True)  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "cloudops_fc.tui", fake)
        assert cli.main(["tui"]) == 0
        assert calls == [True]


class TestCliEval:
    """The quick-eval path MUST aggregate the five built-in cases."""

    def test_eval_counts_exact_matches(self, capsys, monkeypatch) -> None:
        responses = {
            "Create a t3.micro server in us-east-1": {
                "name": "create_ec2_instance",
                "arguments": {"region": "us-east-1", "instance_type": "t3.micro"},
            },
            "Restart the production database in us-west-2": {
                "name": "restart_database",
                "arguments": {
                    "db_instance_identifier": "production",
                    "region": "us-west-2",
                },
            },
            "How much did we spend this month?": {
                "name": "get_billing_alert",
                "arguments": {"granularity": "MONTHLY"},
            },
            "Create a server with port 80 open": {
                "name": "create_ec2_instance",
                "arguments": {
                    "region": "us-east-1",
                    "instance_type": "t3.micro",
                    "security_group_rules": [
                        {"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"}
                    ],
                },
            },
            "Restart analytics-db with failover": {
                "name": "restart_database",
                "arguments": {
                    "db_instance_identifier": "analytics-db",
                    "region": "us-east-1",
                    "force_failover": True,
                },
            },
        }
        monkeypatch.setattr(cli, "infer", lambda prompt, cfg: responses[prompt])
        code = cli.main(["--eval"])
        out = capsys.readouterr().out
        assert code == 0
        assert "Tool accuracy: 5/5 = 100%" in out
        assert "Field accuracy: 11/11 = 100.0%" in out
        assert "Exact match: 5/5 = 100%" in out
