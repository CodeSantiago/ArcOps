"""Tests for the shared ArcOps engine (cloudops_fc.core).

``core.create()`` must run infer → safety check → execute without needing
the ML stack or a real AWS/LocalStack installation; inference and the AWS
CLI are monkeypatched in these tests.
"""

from __future__ import annotations

from cloudops_fc import core


def _ec2_call() -> dict:
    return {
        "name": "create_ec2_instance",
        "arguments": {"region": "us-east-1", "instance_type": "t3.micro"},
    }


class TestCoreCreate:
    """create() must safety-check before executing."""

    def test_create_blocks_unknown_tool(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(core, "infer", lambda prompt, cfg: {"name": "nope", "arguments": {}})
        monkeypatch.setattr(core, "ls_check", lambda: True)
        monkeypatch.setattr(core, "REAL", False)
        status, msg = core.create("nonsense prompt")
        out = capsys.readouterr().out
        assert status == "blocked"
        assert "Blocked by safety policy" in msg
        assert "Unknown tool" in out

    def test_create_ok_runs_aws(self, monkeypatch) -> None:
        monkeypatch.setattr(core, "infer", lambda prompt, cfg: _ec2_call())
        monkeypatch.setattr(core, "ls_check", lambda: True)
        monkeypatch.setattr(core, "REAL", False)
        monkeypatch.setattr(
            core,
            "aws",
            lambda args: {"Instances": [{"InstanceId": "i-1234"}]},
        )
        status, msg = core.create("create a server")
        assert status == "ok"
        assert "i-1234" in msg

    def test_create_cancelled_when_real_without_callback(self, monkeypatch) -> None:
        """Real-AWS actions need a confirm callback; without one, refuse."""
        monkeypatch.setattr(core, "infer", lambda prompt, cfg: _ec2_call())
        monkeypatch.setattr(core, "REAL", True)
        status, msg = core.create("create a server")
        assert status == "cancelled"
        assert "confirm" in msg.lower()

    def test_create_confirm_callback_declines(self, monkeypatch) -> None:
        monkeypatch.setattr(core, "infer", lambda prompt, cfg: _ec2_call())
        monkeypatch.setattr(core, "REAL", True)
        status, msg = core.create("create a server", confirm_callable=lambda m: False)
        assert status == "cancelled"
        assert msg == "Cancelled"

    def test_create_confirm_callback_approves(self, monkeypatch) -> None:
        monkeypatch.setattr(core, "infer", lambda prompt, cfg: _ec2_call())
        monkeypatch.setattr(core, "REAL", True)
        monkeypatch.setattr(
            core,
            "aws",
            lambda args: {"Instances": [{"InstanceId": "i-5678"}]},
        )
        status, msg = core.create("create a server", confirm_callable=lambda m: True)
        assert status == "ok"
        assert "i-5678" in msg
