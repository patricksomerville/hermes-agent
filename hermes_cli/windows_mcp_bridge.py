"""Windows-side MCP bridge for Hermes running from WSL.

This module is intentionally Windows-native. Run it on the Windows host, then
point a WSL Hermes install at ``http://<windows-host>:48779/sse`` using the
normal ``mcp_servers.windows`` config entry.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from typing import Any

logger = logging.getLogger("hermes.windows_mcp_bridge")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 48779
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600

_MCP_SERVER_AVAILABLE = False
try:
    from mcp.server.fastmcp import FastMCP

    _MCP_SERVER_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised in installs without [mcp]
    FastMCP = None  # type: ignore[assignment,misc]


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError(
            "The Windows MCP bridge must run on the Windows host. "
            "Run Hermes inside WSL as the MCP client, not as this server."
        )


def _coerce_timeout(value: int | float | str | None) -> int:
    try:
        timeout = int(value if value is not None else DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    return max(1, min(timeout, MAX_TIMEOUT))


def _ps_quote(value: Any) -> str:
    """Return a PowerShell single-quoted string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def _ps_value(value: Any, value_type: str = "String") -> str:
    normalized = _normalize_registry_value_type(value_type)
    if normalized in {"DWord", "QWord"}:
        return str(int(value))
    if normalized == "MultiString" and isinstance(value, (list, tuple)):
        return "@(" + ",".join(_ps_quote(item) for item in value) + ")"
    if normalized == "Binary" and isinstance(value, (bytes, bytearray, list, tuple)):
        return "([byte[]]@(" + ",".join(str(int(item)) for item in value) + "))"
    return _ps_quote(value)


def _decode_json_output(stdout: str) -> Any:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return text


def _run_process(
    args: list[str],
    *,
    timeout: int | float | str | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    _require_windows()
    run_kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": _coerce_timeout(timeout),
    }
    if cwd:
        run_kwargs["cwd"] = cwd
    if sys.platform == "win32":
        run_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    try:
        proc = subprocess.run(args, **run_kwargs)
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or f"Timed out after {run_kwargs['timeout']}s",
            "command": args,
        }
    except OSError as exc:
        return {
            "ok": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": str(exc),
            "command": args,
        }

    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
        "command": args,
    }


def _powershell(
    command: str,
    *,
    timeout: int | float | str | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    return _run_process(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        timeout=timeout,
        cwd=cwd,
    )


def _with_json_result(result: dict[str, Any]) -> dict[str, Any]:
    updated = dict(result)
    updated["result"] = _decode_json_output(updated.get("stdout", ""))
    return updated


def windows_exec(
    command: str,
    shell: str = "powershell",
    timeout: int = DEFAULT_TIMEOUT,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Run a Windows command through PowerShell or cmd.exe."""
    if not isinstance(command, str) or not command.strip():
        return {"ok": False, "error": "command is required"}

    shell_normalized = (shell or "powershell").strip().lower()
    if shell_normalized in {"powershell", "ps", "pwsh"}:
        result = _powershell(command, timeout=timeout, cwd=cwd)
    elif shell_normalized in {"cmd", "cmd.exe"}:
        result = _run_process(
            ["cmd.exe", "/d", "/s", "/c", command],
            timeout=timeout,
            cwd=cwd,
        )
    else:
        return {"ok": False, "error": "shell must be 'powershell' or 'cmd'"}

    result["shell"] = shell_normalized
    return result


def windows_service(
    action: str,
    name: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Query or manage a Windows service by service name."""
    if not name:
        return {"ok": False, "error": "service name is required"}
    normalized = (action or "status").strip().lower()
    action_map = {"get": "status", "query": "status", "start": "start", "stop": "stop", "restart": "restart"}
    normalized = action_map.get(normalized, normalized)
    if normalized not in {"status", "start", "stop", "restart"}:
        return {"ok": False, "error": "action must be status, start, stop, or restart"}

    svc = _ps_quote(name)
    if normalized == "start":
        prefix = f"Start-Service -Name {svc} -ErrorAction Stop;"
    elif normalized == "stop":
        prefix = f"Stop-Service -Name {svc} -ErrorAction Stop;"
    elif normalized == "restart":
        prefix = f"Restart-Service -Name {svc} -Force -ErrorAction Stop;"
    else:
        prefix = ""

    command = (
        f"{prefix}"
        f"Get-Service -Name {svc} -ErrorAction Stop | "
        "Select-Object Name,DisplayName,Status,ServiceType,StartType | "
        "ConvertTo-Json -Compress"
    )
    result = _with_json_result(_powershell(command, timeout=timeout))
    result["action"] = normalized
    return result


_REGISTRY_ROOTS = {
    "HKEY_LOCAL_MACHINE": "HKLM:",
    "HKLM": "HKLM:",
    "HKEY_CURRENT_USER": "HKCU:",
    "HKCU": "HKCU:",
    "HKEY_CLASSES_ROOT": "HKCR:",
    "HKCR": "HKCR:",
    "HKEY_USERS": "HKU:",
    "HKU": "HKU:",
    "HKEY_CURRENT_CONFIG": "HKCC:",
    "HKCC": "HKCC:",
}


def _normalize_registry_value_type(value_type: str) -> str:
    normalized = (value_type or "String").strip().lower()
    return {
        "string": "String",
        "expandstring": "ExpandString",
        "expand_string": "ExpandString",
        "binary": "Binary",
        "dword": "DWord",
        "multi_string": "MultiString",
        "multistring": "MultiString",
        "qword": "QWord",
    }.get(normalized, value_type)


def _normalize_registry_path(path: str) -> str:
    text = str(path or "").strip().replace("/", "\\")
    if not text:
        raise ValueError("registry path is required")
    if re.match(r"^[A-Za-z]+:\\", text):
        return text
    root, sep, rest = text.partition("\\")
    prefix = _REGISTRY_ROOTS.get(root.upper())
    if not prefix:
        raise ValueError(
            "registry path must start with HKLM, HKCU, HKCR, HKU, HKCC, "
            "or a full HKEY_* root"
        )
    return prefix + ("\\" + rest if sep else "\\")


def windows_registry(
    action: str,
    path: str,
    key: str | None = None,
    value: Any = None,
    value_type: str = "String",
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Query, set, or delete a Windows registry value."""
    try:
        reg_path = _normalize_registry_path(path)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    normalized = (action or "get").strip().lower()
    normalized = {"query": "get", "read": "get", "remove": "delete"}.get(normalized, normalized)
    path_expr = _ps_quote(reg_path)

    if normalized == "get":
        if key:
            command = (
                f"Get-ItemProperty -LiteralPath {path_expr} -Name {_ps_quote(key)} "
                "-ErrorAction Stop | "
                f"Select-Object -ExpandProperty {_ps_quote(key)} | "
                "ConvertTo-Json -Compress"
            )
        else:
            command = (
                f"Get-ItemProperty -LiteralPath {path_expr} -ErrorAction Stop | "
                "ConvertTo-Json -Compress"
            )
    elif normalized == "set":
        if not key:
            return {"ok": False, "error": "key is required for set"}
        allowed_types = {"String", "ExpandString", "Binary", "DWord", "MultiString", "QWord"}
        value_type = _normalize_registry_value_type(value_type)
        if value_type not in allowed_types:
            return {"ok": False, "error": f"value_type must be one of {sorted(allowed_types)}"}
        command = (
            f"New-ItemProperty -LiteralPath {path_expr} -Name {_ps_quote(key)} "
            f"-Value {_ps_value(value, value_type)} -PropertyType {value_type} "
            "-Force -ErrorAction Stop | ConvertTo-Json -Compress"
        )
    elif normalized == "delete":
        if not key:
            return {"ok": False, "error": "key is required for delete"}
        command = (
            f"Remove-ItemProperty -LiteralPath {path_expr} -Name {_ps_quote(key)} "
            "-ErrorAction Stop; "
            f"Get-ItemProperty -LiteralPath {path_expr} -ErrorAction Stop | "
            "ConvertTo-Json -Compress"
        )
    else:
        return {"ok": False, "error": "action must be get, set, or delete"}

    result = _with_json_result(_powershell(command, timeout=timeout))
    result["action"] = normalized
    return result


def _firewall_selector(rule: str | None, display_name: str | None) -> str:
    if rule:
        return f"-Name {_ps_quote(rule)}"
    if display_name:
        return f"-DisplayName {_ps_quote(display_name)}"
    return ""


def windows_firewall(
    action: str,
    rule: str | None = None,
    display_name: str | None = None,
    port: int | None = None,
    protocol: str = "TCP",
    direction: str = "Inbound",
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """List or manage Windows Defender Firewall rules."""
    normalized = (action or "list").strip().lower()
    normalized = {"get": "list", "remove": "delete", "allow-port": "allow_port"}.get(normalized, normalized)
    selector = _firewall_selector(rule, display_name)

    if normalized == "list":
        command = (
            f"Get-NetFirewallRule {selector} -ErrorAction Stop | "
            "Select-Object -First 100 Name,DisplayName,Enabled,Direction,Action,Profile | "
            "ConvertTo-Json -Compress"
        )
    elif normalized in {"enable", "disable", "delete"}:
        if not selector:
            return {"ok": False, "error": "rule or display_name is required"}
        verb = {
            "enable": "Enable-NetFirewallRule",
            "disable": "Disable-NetFirewallRule",
            "delete": "Remove-NetFirewallRule",
        }[normalized]
        command = f"{verb} {selector} -ErrorAction Stop"
    elif normalized == "allow_port":
        if port is None:
            return {"ok": False, "error": "port is required for allow_port"}
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            return {"ok": False, "error": "port must be an integer"}
        if port_int < 1 or port_int > 65535:
            return {"ok": False, "error": "port must be between 1 and 65535"}
        proto = (protocol or "TCP").upper()
        if proto not in {"TCP", "UDP"}:
            return {"ok": False, "error": "protocol must be TCP or UDP"}
        dir_value = (direction or "Inbound").capitalize()
        if dir_value not in {"Inbound", "Outbound"}:
            return {"ok": False, "error": "direction must be Inbound or Outbound"}
        name = display_name or rule or f"Hermes Windows MCP {port_int}"
        command = (
            f"$existing = Get-NetFirewallRule -DisplayName {_ps_quote(name)} "
            "-ErrorAction SilentlyContinue; "
            "if ($existing) { "
            "$existing | Set-NetFirewallRule -Enabled True -Action Allow -ErrorAction Stop "
            "} else { "
            f"New-NetFirewallRule -DisplayName {_ps_quote(name)} -Direction {dir_value} "
            f"-Action Allow -Protocol {proto} -LocalPort {port_int} -ErrorAction Stop | Out-Null "
            "}; "
            f"Get-NetFirewallRule -DisplayName {_ps_quote(name)} -ErrorAction Stop | "
            "Select-Object Name,DisplayName,Enabled,Direction,Action,Profile | "
            "ConvertTo-Json -Compress"
        )
    else:
        return {
            "ok": False,
            "error": "action must be list, enable, disable, delete, or allow_port",
        }

    result = _with_json_result(_powershell(command, timeout=timeout))
    result["action"] = normalized
    return result


def windows_schedule(
    action: str,
    name: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """List, query, run, stop, enable, disable, or delete a scheduled task."""
    normalized = (action or "list").strip().lower()
    normalized = {"get": "query", "start": "run", "end": "stop", "remove": "delete"}.get(normalized, normalized)

    if normalized == "list":
        command = (
            "Get-ScheduledTask | Select-Object -First 100 TaskName,TaskPath,State | "
            "ConvertTo-Json -Compress"
        )
    else:
        if not name:
            return {"ok": False, "error": "name is required"}
        task = _ps_quote(name)
        if normalized == "query":
            command = (
                f"Get-ScheduledTask -TaskName {task} -ErrorAction Stop | "
                "Select-Object TaskName,TaskPath,State | ConvertTo-Json -Compress"
            )
        elif normalized == "run":
            command = f"Start-ScheduledTask -TaskName {task} -ErrorAction Stop"
        elif normalized == "stop":
            command = f"Stop-ScheduledTask -TaskName {task} -ErrorAction Stop"
        elif normalized == "enable":
            command = f"Enable-ScheduledTask -TaskName {task} -ErrorAction Stop | ConvertTo-Json -Compress"
        elif normalized == "disable":
            command = f"Disable-ScheduledTask -TaskName {task} -ErrorAction Stop | ConvertTo-Json -Compress"
        elif normalized == "delete":
            command = f"Unregister-ScheduledTask -TaskName {task} -Confirm:$false -ErrorAction Stop"
        else:
            return {
                "ok": False,
                "error": "action must be list, query, run, stop, enable, disable, or delete",
            }

    result = _with_json_result(_powershell(command, timeout=timeout))
    result["action"] = normalized
    return result


def create_windows_mcp_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> "FastMCP":
    """Create the Windows MCP server with its SSE endpoint at ``/sse``."""
    if not _MCP_SERVER_AVAILABLE:
        raise RuntimeError("Windows MCP bridge requires the 'mcp' package")

    server = FastMCP(
        "windows",
        host=host,
        port=int(port),
        sse_path="/sse",
        message_path="/messages/",
        log_level="INFO",
    )

    server.tool(
        name="windows_exec",
        description="Run a Windows command through PowerShell or cmd.exe.",
    )(windows_exec)
    server.tool(
        name="windows_service",
        description="Query, start, stop, or restart a Windows service.",
    )(windows_service)
    server.tool(
        name="windows_registry",
        description="Query, set, or delete a Windows registry value.",
    )(windows_registry)
    server.tool(
        name="windows_firewall",
        description="List or manage Windows Defender Firewall rules.",
    )(windows_firewall)
    server.tool(
        name="windows_schedule",
        description="List or manage Windows scheduled tasks.",
    )(windows_schedule)

    return server


def run_windows_mcp_bridge(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    verbose: bool = False,
) -> None:
    """Run the Windows MCP bridge over SSE."""
    if not _MCP_SERVER_AVAILABLE:
        print(
            "Error: Windows MCP bridge requires the 'mcp' package.\n"
            f"Install with: {sys.executable} -m pip install 'mcp'",
            file=sys.stderr,
        )
        raise SystemExit(1)

    _require_windows()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        stream=sys.stderr,
    )
    logger.info("Starting Windows MCP bridge on http://%s:%s/sse", host, port)
    create_windows_mcp_server(host=host, port=port).run("sse")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Hermes Windows MCP bridge over SSE")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port (default: {DEFAULT_PORT})")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    run_windows_mcp_bridge(host=args.host, port=args.port, verbose=args.verbose)


if __name__ == "__main__":  # pragma: no cover
    main()
