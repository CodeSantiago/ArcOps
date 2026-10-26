"""Protocol tests for the MCP server (no ML stack required)."""

from __future__ import annotations

from scripts import mcp_server


class TestMcpProtocol:
    def test_initialize_uses_a_dated_protocol_version(self) -> None:
        response = mcp_server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        })
        assert response is not None
        version = response["result"]["protocolVersion"]
        assert version != "0.1.0"
        assert version.count("-") == 2

    def test_tools_list_exposes_both_tools(self) -> None:
        response = mcp_server.handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        })
        assert response is not None
        names = {tool["name"] for tool in response["result"]["tools"]}
        assert names == {"cloudops_plan", "cloudops_execute"}

    def test_notifications_do_not_get_a_response(self) -> None:
        response = mcp_server.handle_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        assert response is None

    def test_ping_returns_empty_result(self) -> None:
        response = mcp_server.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "ping",
        })
        assert response == {"jsonrpc": "2.0", "id": 3, "result": {}}

    def test_unknown_tool_is_rejected_before_inference(self) -> None:
        response = mcp_server.handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "not_a_tool", "arguments": {"prompt": "hello"}},
        })
        assert response is not None
        assert response["error"]["code"] == -32602

    def test_missing_prompt_is_rejected(self) -> None:
        response = mcp_server.handle_request({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "cloudops_plan", "arguments": {}},
        })
        assert response is not None
        assert response["error"]["code"] == -32602

    def test_unknown_method_returns_method_not_found(self) -> None:
        response = mcp_server.handle_request({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "resources/list",
        })
        assert response is not None
        assert response["error"]["code"] == -32601

    def test_non_object_request_is_rejected(self) -> None:
        response = mcp_server.handle_request(["not", "an", "object"])  # type: ignore[arg-type]
        assert response is not None
        assert response["error"]["code"] == -32600

    def test_non_object_arguments_are_rejected(self) -> None:
        response = mcp_server.handle_request({
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "cloudops_plan", "arguments": ["nope"]},
        })
        assert response is not None
        assert response["error"]["code"] == -32602

    def test_inference_error_marks_tool_result_as_error(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            mcp_server, "generate_tool_call", lambda prompt: {"error": "boom"}
        )
        response = mcp_server.handle_request({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "cloudops_plan",
                "arguments": {"prompt": "hello"},
            },
        })
        assert response is not None
        assert response["result"].get("isError") is True

    def test_disruptive_execution_is_refused_without_approval(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(mcp_server, "REAL", False)
        result = mcp_server.execute_on_localstack({
            "name": "restart_database",
            "arguments": {
                "db_instance_identifier": "prod-db",
                "region": "us-east-1",
            },
        })
        assert result["status"] == "cancelled"
        assert "Confirmation required" in result["message"]
