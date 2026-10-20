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


def _ec2_call_with_rules() -> dict:
    return {
        "name": "create_ec2_instance",
        "arguments": {
            "region": "us-east-1",
            "instance_type": "t3.micro",
            "security_group_rules": [
                {"port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0"}
            ],
        },
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

    def test_create_applies_security_group_rules(self, monkeypatch) -> None:
        calls: list[list[str]] = []

        def fake_aws(args: list[str]) -> dict:
            calls.append(args)
            if args[0:2] == ["ec2", "create-security-group"]:
                return {"GroupId": "sg-123"}
            if args[0:2] == ["ec2", "authorize-security-group-ingress"]:
                return {}
            if args[0:2] == ["ec2", "run-instances"]:
                return {"Instances": [{"InstanceId": "i-1234"}]}
            return {}

        monkeypatch.setattr(core, "infer", lambda prompt, cfg: _ec2_call_with_rules())
        monkeypatch.setattr(core, "ls_check", lambda: True)
        monkeypatch.setattr(core, "REAL", False)
        monkeypatch.setattr(core, "aws", fake_aws)

        status, _msg = core.create("create a server with port 80")
        assert status == "ok"

        auth = [c for c in calls if c[0:2] == ["ec2", "authorize-security-group-ingress"]]
        assert len(auth) == 1
        assert "--port" in auth[0]
        assert "80" in auth[0]

        run = [c for c in calls if c[0:2] == ["ec2", "run-instances"]][0]
        assert "--security-group-ids" in run
        assert "sg-123" in run

    def test_failed_launch_cleans_up_security_group(self, monkeypatch) -> None:
        calls: list[list[str]] = []

        def fake_aws(args: list[str]) -> dict | None:
            calls.append(args)
            if args[0:2] == ["ec2", "create-security-group"]:
                return {"GroupId": "sg-123"}
            if args[0:2] == ["ec2", "authorize-security-group-ingress"]:
                return {}
            if args[0:2] == ["ec2", "run-instances"]:
                return None
            return {}

        monkeypatch.setattr(core, "infer", lambda prompt, cfg: _ec2_call_with_rules())
        monkeypatch.setattr(core, "ls_check", lambda: True)
        monkeypatch.setattr(core, "REAL", False)
        monkeypatch.setattr(core, "aws", fake_aws)

        status, _msg = core.create("create a server with port 80")
        assert status == "error"
        assert any(c[0:2] == ["ec2", "delete-security-group"] for c in calls)


class TestCommandBuilders:
    """The AWS CLI builders must include every supported argument."""

    def test_run_instances_includes_all_supported_args(self) -> None:
        args = {
            "region": "us-west-2",
            "instance_type": "t3.small",
            "ami_id": "ami-123",
            "key_name": "my-key",
            "subnet_id": "subnet-1",
            "min_count": 2,
            "max_count": 3,
            "associate_public_ip": True,
            "security_group_rules": [{"port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0"}],
            "tags": [{"key": "Name", "value": "web"}],
        }
        command = core.build_run_instances_cmd(args, "sg-1")

        assert command[:3] == ["ec2", "run-instances", "--region"]
        assert "--image-id" in command
        assert "ami-123" in command
        assert "--key-name" in command
        assert "--subnet-id" in command
        assert command[command.index("--min-count") + 1] == "2"
        assert command[command.index("--max-count") + 1] == "3"
        assert "--associate-public-ip-address" in command
        assert command[command.index("--security-group-ids") + 1] == "sg-1"

        tag_spec = command[command.index("--tag-specifications") + 1]
        assert '"Key":"Name"' in tag_spec
        assert '"Value":"web"' in tag_spec

    def test_reboot_db_includes_force_failover(self) -> None:
        command = core.build_reboot_db_cmd({
            "db_instance_identifier": "db-1",
            "region": "us-east-1",
            "force_failover": True,
        })
        assert "--force-failover" in command

        no_failover = core.build_reboot_db_cmd({
            "db_instance_identifier": "db-1",
            "region": "us-east-1",
            "force_failover": False,
        })
        assert "--force-failover" not in no_failover


class TestCoreActions:
    """Resource actions must be explicit and safe."""

    def test_act_refuses_rds_stop(self, monkeypatch) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(core, "aws", lambda args: calls.append(args))
        status, msg = core.act(
            {"t": "RDS", "id": "db-1"},
            "stop-instances",
            confirm_callable=lambda message: True,
        )
        assert status == "error"
        assert "does not support" in msg
        assert calls == []

    def test_act_refuses_delete_without_confirmation(self, monkeypatch) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(core, "aws", lambda args: calls.append(args))
        status, _msg = core.act({"t": "RDS", "id": "db-1"}, "delete-db-instance")
        assert status == "cancelled"
        assert calls == []

    def test_tag_it_preserves_other_tags(self, monkeypatch) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(core, "aws", lambda args: calls.append(args) or {})
        status, _msg = core.tag_it({"t": "EC2", "id": "i-1"}, "Name", "web")
        assert status == "ok"
        assert any("create-tags" in call for call in calls)
        assert not any("delete-tags" in call for call in calls)


class TestExecuteToolCall:
    """execute_tool_call must apply safety and pass tool options."""

    def test_unknown_tool_is_blocked(self) -> None:
        status, msg = core.execute_tool_call("nope", {}, verbose=False)
        assert status == "blocked"
        assert "Blocked" in msg

    def test_restart_passes_force_failover(self, monkeypatch) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(core, "aws", lambda args: calls.append(args) or {})
        monkeypatch.setattr(core, "REAL", False)
        status, _msg = core.execute_tool_call(
            "restart_database",
            {
                "db_instance_identifier": "db-1",
                "region": "us-east-1",
                "force_failover": True,
            },
            confirm_callable=lambda message: True,
            verbose=False,
        )
        assert status == "ok"
        assert "--force-failover" in calls[0]
