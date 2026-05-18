from types import SimpleNamespace

import pytest

from hermes_cli import windows_mcp_bridge as bridge


class _FakeFastMCP:
    def __init__(self, name, **kwargs):
        self.name = name
        self.kwargs = kwargs
        self.tools = {}
        self.run_calls = []

    def tool(self, name=None, **_kwargs):
        def _decorate(fn):
            self.tools[name or fn.__name__] = fn
            return fn

        return _decorate

    def run(self, transport="stdio"):
        self.run_calls.append(transport)


def test_create_server_defaults_to_windows_sse_endpoint(monkeypatch):
    monkeypatch.setattr(bridge, "_MCP_SERVER_AVAILABLE", True)
    monkeypatch.setattr(bridge, "FastMCP", _FakeFastMCP)

    server = bridge.create_windows_mcp_server()

    assert server.name == "windows"
    assert server.kwargs["host"] == "127.0.0.1"
    assert server.kwargs["port"] == 48779
    assert server.kwargs["sse_path"] == "/sse"
    assert server.kwargs["message_path"] == "/messages/"
    assert set(server.tools) == {
        "windows_exec",
        "windows_service",
        "windows_registry",
        "windows_firewall",
        "windows_schedule",
    }


def test_run_bridge_uses_sse_transport(monkeypatch):
    fake_server = _FakeFastMCP("windows")

    monkeypatch.setattr(bridge.sys, "platform", "win32")
    monkeypatch.setattr(bridge, "_MCP_SERVER_AVAILABLE", True)
    monkeypatch.setattr(
        bridge,
        "create_windows_mcp_server",
        lambda **kwargs: fake_server,
    )

    bridge.run_windows_mcp_bridge(host="0.0.0.0", port=48779)

    assert fake_server.run_calls == ["sse"]


def test_windows_exec_builds_powershell_invocation(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(bridge.sys, "platform", "win32")
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    result = bridge.windows_exec("Get-Process -Id $PID", timeout=5)

    assert result["ok"] is True
    assert result["stdout"] == "ok"
    assert captured["args"][:6] == [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
    ]
    assert captured["args"][-1] == "Get-Process -Id $PID"
    assert captured["kwargs"]["timeout"] == 5


def test_service_status_parses_json(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["command"] = args[-1]
        return SimpleNamespace(
            returncode=0,
            stdout='{"Name":"Spooler","Status":"Running"}',
            stderr="",
        )

    monkeypatch.setattr(bridge.sys, "platform", "win32")
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    result = bridge.windows_service("query", "Spooler")

    assert result["ok"] is True
    assert result["action"] == "status"
    assert result["result"] == {"Name": "Spooler", "Status": "Running"}
    assert "Get-Service -Name 'Spooler'" in captured["command"]


def test_registry_normalizes_hkey_paths_for_query(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["command"] = args[-1]
        return SimpleNamespace(returncode=0, stdout='"value"', stderr="")

    monkeypatch.setattr(bridge.sys, "platform", "win32")
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    result = bridge.windows_registry(
        "get",
        r"HKEY_CURRENT_USER\Software\Hermes",
        key="Enabled",
    )

    assert result["ok"] is True
    assert result["result"] == "value"
    assert "'HKCU:\\Software\\Hermes'" in captured["command"]
    assert "Select-Object -ExpandProperty 'Enabled'" in captured["command"]


def test_firewall_allow_port_builds_rule(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["command"] = args[-1]
        return SimpleNamespace(
            returncode=0,
            stdout='{"DisplayName":"Hermes Windows MCP 48779","Enabled":"True"}',
            stderr="",
        )

    monkeypatch.setattr(bridge.sys, "platform", "win32")
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    result = bridge.windows_firewall("allow_port", port=48779)

    assert result["ok"] is True
    assert result["result"]["DisplayName"] == "Hermes Windows MCP 48779"
    assert "New-NetFirewallRule" in captured["command"]
    assert "-LocalPort 48779" in captured["command"]


def test_schedule_run_builds_scheduled_task_command(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["command"] = args[-1]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(bridge.sys, "platform", "win32")
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    result = bridge.windows_schedule("run", name="Hermes_Gateway")

    assert result["ok"] is True
    assert "Start-ScheduledTask -TaskName 'Hermes_Gateway'" in captured["command"]


def test_mcp_dispatches_windows_bridge(monkeypatch):
    from hermes_cli import mcp_config

    called = {}

    def fake_run_windows_mcp_bridge(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(
        "hermes_cli.windows_mcp_bridge.run_windows_mcp_bridge",
        fake_run_windows_mcp_bridge,
    )

    mcp_config.mcp_command(
        SimpleNamespace(
            mcp_action="windows-bridge",
            host="0.0.0.0",
            port=48779,
            verbose=True,
        )
    )

    assert called == {"host": "0.0.0.0", "port": 48779, "verbose": True}


def test_bridge_refuses_to_run_off_windows(monkeypatch):
    monkeypatch.setattr(bridge.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows host"):
        bridge.run_windows_mcp_bridge()
