#!/usr/bin/env python3
"""Run a real Keycloak-authenticated MCP acceptance demo against the deployed server.

The script uses only the Python standard library. It never prints or persists the
access token or client secret.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import ssl
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

DEFAULT_ISSUER = "https://auth.home.arpa/realms/linux-agent"
DEFAULT_RESOURCE = "https://mcp.home.arpa/mcp"
DEFAULT_ENDPOINT = DEFAULT_RESOURCE
PROTOCOL_VERSION = "2025-11-25"
EXPECTED_TOOLS = {
    "get_system_metrics",
    "get_swap_usage",
    "get_disk_usage",
    "get_filesystem_inode_usage",
    "list_processes",
    "read_allowed_log",
    "get_network_stats",
    "get_resource_pressure",
    "get_service_status",
    "check_port",
    "get_system_alerts",
}


class DemoError(RuntimeError):
    """A safe, user-facing demo failure."""


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE entries without executing the file as shell code."""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()

        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key or key in os.environ:
            continue

        try:
            parts = shlex.split(value.strip(), comments=True, posix=True)
        except ValueError as exc:
            raise DemoError(f"Cannot parse {key} in {path}: {exc}") from exc
        os.environ[key] = " ".join(parts)


def discover_caddy_root_ca(repo_root: Path) -> str | None:
    """Read Caddy's local root CA from the running Compose service, if available."""
    compose_file = repo_root / "deploy/compose/compose.yaml"
    if not compose_file.is_file():
        return None

    compose_env = Path(
        os.getenv(
            "LINUX_MCP_COMPOSE_ENV_FILE",
            str(repo_root / "deploy/compose/.env"),
        )
    ).expanduser()

    command = ["docker", "compose"]
    if compose_env.is_file():
        command.extend(["--env-file", str(compose_env)])
    command.extend(
        [
            "-f",
            str(compose_file),
            "--profile",
            "lan",
            "exec",
            "-T",
            "caddy",
            "cat",
            "/data/caddy/pki/authorities/local/root.crt",
        ]
    )

    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    certificate = result.stdout.strip()
    if result.returncode != 0 or "-----BEGIN CERTIFICATE-----" not in certificate:
        return None
    return certificate + "\n"


def make_opener(ca_cert: str | None, repo_root: Path) -> tuple[Any, str]:
    """Build a verified HTTPS opener; local .home.arpa traffic must not use proxies."""
    configured_ca = ca_cert or os.getenv("MCP_DEMO_CA_CERT")
    if configured_ca:
        ca_path = Path(configured_ca).expanduser()
        try:
            context = ssl.create_default_context(cafile=str(ca_path))
        except (OSError, ssl.SSLError) as exc:
            raise DemoError(f"Cannot load CA certificate {ca_path}: {exc}") from exc
        trust_source = f"CA certificate file: {ca_path}"
    else:
        caddy_root_ca = discover_caddy_root_ca(repo_root)
        if caddy_root_ca:
            try:
                context = ssl.create_default_context(cadata=caddy_root_ca)
            except ssl.SSLError as exc:
                raise DemoError(f"Caddy root CA is invalid: {exc}") from exc
            trust_source = "Caddy internal root CA (read from Docker Compose)"
        else:
            context = ssl.create_default_context()
            trust_source = "system certificate store"

    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
    return opener, trust_source


def read_json_response(response: Any, *, context: str) -> dict[str, Any]:
    try:
        payload = json.loads(response.read(1_048_576).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DemoError(f"{context}: server returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise DemoError(f"{context}: server returned an unexpected response")
    return payload


def get_client_credentials() -> tuple[str, str]:
    client_id = (
        os.getenv("MCP_DEMO_CLIENT_ID")
        or os.getenv("MCP_AGENT_CLIENT_ID")
        or os.getenv("KEYCLOAK_AGENT_CLIENT_ID")
        or ""
    ).strip()
    client_secret = (
        os.getenv("MCP_DEMO_CLIENT_SECRET")
        or os.getenv("MCP_AGENT_CLIENT_SECRET")
        or os.getenv("KEYCLOAK_AGENT_CLIENT_SECRET")
        or ""
    )
    if not client_id or not client_secret:
        raise DemoError(
            "Missing agent client credentials. Set MCP_AGENT_CLIENT_ID and "
            "MCP_AGENT_CLIENT_SECRET in ~/.config/linux-mcp-agent/keycloak-clients.env."
        )
    return client_id, client_secret


def request_access_token(
    opener: Any,
    *,
    token_url: str,
    resource: str,
    timeout: float,
) -> tuple[str, str]:
    client_id, client_secret = get_client_credentials()
    form = urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "mcp.read mcp.logs.read",
            "resource": resource,
        }
    ).encode("utf-8")
    request = Request(
        token_url,
        data=form,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with opener.open(request, timeout=timeout) as response:
            payload = read_json_response(response, context="Keycloak token request")
    except HTTPError as exc:
        raise DemoError(f"Keycloak token request failed with HTTP {exc.code}") from None
    except URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise DemoError(
                "Keycloak TLS certificate is not trusted. The script can read the Caddy "
                "root CA from Docker Compose, or use --ca-cert /path/to/root.crt."
            ) from None
        raise DemoError(f"Cannot reach Keycloak token endpoint: {exc.reason}") from None
    except TimeoutError:
        raise DemoError("Keycloak token request timed out") from None

    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        error = payload.get("error_description") or payload.get("error")
        if isinstance(error, str):
            raise DemoError(f"Keycloak did not issue an access token: {error}")
        raise DemoError("Keycloak response did not contain an access token")

    granted_scope = payload.get("scope")
    if not isinstance(granted_scope, str):
        granted_scope = "scope not reported by token endpoint"
    return token, granted_scope


def decode_sse(body: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []

    def flush() -> None:
        if not data_lines:
            return
        data = "\n".join(data_lines)
        data_lines.clear()
        if data == "[DONE]":
            return
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            return
        if isinstance(message, dict):
            messages.append(message)

    for line in body.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif not line:
            flush()
    flush()
    return messages


class StreamableHttpMcpClient:
    """Small JSON-RPC client for the MCP Streamable HTTP transport."""

    def __init__(
        self,
        opener: Any,
        *,
        endpoint: str,
        token: str,
        timeout: float,
    ) -> None:
        self._opener = opener
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 1

    def _post(self, message: dict[str, Any], *, expect_response: bool) -> dict[str, Any] | None:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        request = Request(
            self.endpoint,
            data=json.dumps(message, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
                body = response.read(2_097_152).decode("utf-8")
                content_type = response.headers.get("Content-Type", "").lower()
        except HTTPError as exc:
            raise DemoError(f"MCP endpoint returned HTTP {exc.code}") from None
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise DemoError(
                    "TLS certificate is not trusted. Install the Caddy local root CA, "
                    "or pass --ca-cert /path/to/root.crt (or set MCP_DEMO_CA_CERT)."
                ) from None
            raise DemoError(f"Cannot reach MCP endpoint: {reason}") from None
        except TimeoutError:
            raise DemoError("MCP request timed out") from None
        except UnicodeDecodeError:
            raise DemoError("MCP endpoint returned non-UTF-8 data") from None

        if not body.strip():
            if expect_response:
                raise DemoError("MCP endpoint returned an empty response")
            return None

        if "text/event-stream" in content_type:
            messages = decode_sse(body)
            if not messages:
                if expect_response:
                    raise DemoError("MCP SSE response did not contain a JSON-RPC message")
                return None
            response_message = messages[-1]
        else:
            try:
                response_message = json.loads(body)
            except json.JSONDecodeError as exc:
                raise DemoError("MCP endpoint returned invalid JSON") from exc

        if isinstance(response_message, list):
            response_message = next(
                (
                    item
                    for item in response_message
                    if isinstance(item, dict) and item.get("id") == message.get("id")
                ),
                None,
            )
        if not isinstance(response_message, dict):
            if expect_response:
                raise DemoError("MCP endpoint returned an unexpected JSON-RPC response")
            return None
        if "error" in response_message:
            error = response_message.get("error")
            if isinstance(error, dict):
                detail = error.get("message", "unknown JSON-RPC error")
            else:
                detail = "unknown JSON-RPC error"
            raise DemoError(f"MCP JSON-RPC error: {detail}")
        return response_message

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        response = self._post(message, expect_response=True)
        if response is None:
            raise DemoError(f"MCP did not answer {method}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise DemoError(f"MCP returned an invalid result for {method}")
        return result

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        self._post(message, expect_response=False)


def result_value(tool_result: dict[str, Any]) -> Any:
    if tool_result.get("isError") is True:
        texts = [
            item.get("text", "")
            for item in tool_result.get("content", [])
            if isinstance(item, dict)
        ]
        detail = " ".join(text for text in texts if isinstance(text, str))
        raise DemoError(detail or "tool returned isError=true")

    structured = tool_result.get("structuredContent")
    if structured is not None:
        return structured

    texts = [
        item.get("text")
        for item in tool_result.get("content", [])
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    ]
    if len(texts) == 1:
        text_value = texts[0]
        try:
            return json.loads(text_value)
        except json.JSONDecodeError:
            return text_value
    if texts:
        return texts
    return tool_result


def print_value(value: Any, *, max_chars: int = 4000) -> None:
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(rendered) > max_chars:
        rendered = rendered[:max_chars].rstrip() + "\n... (output truncated for demo)"
    print(rendered)


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text_value = content.get("text")
        if isinstance(text_value, str):
            return text_value
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        return "\n".join(extract_text(item) for item in content)
    return str(content)


def run_acceptance_demo(client: StreamableHttpMcpClient) -> tuple[int, int]:
    passed = 0
    failed = 0

    def record(label: str, action: Any) -> Any:
        nonlocal passed, failed
        print(f"\n--- {label} ---")
        try:
            value = action()
        except DemoError as exc:
            failed += 1
            print(f"FAIL: {exc}")
            return None
        passed += 1
        print("PASS")
        return value

    initialized = client.rpc(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "linux-mcp-live-demo", "version": "1.0.0"},
        },
    )
    server_info = initialized.get("serverInfo", {})
    print(
        "PASS: MCP Initialize "
        f"(protocol={initialized.get('protocolVersion', PROTOCOL_VERSION)}, "
        f"server={server_info.get('name', 'unknown')})"
    )
    passed += 1

    record("Initialized notification", lambda: client.notify("notifications/initialized"))

    tools_result = record("Tools discovery", lambda: client.rpc("tools/list"))
    discovered_tools: set[str] = set()
    if tools_result is not None:
        discovered_tools = {
            item.get("name")
            for item in tools_result.get("tools", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        print("Discovered tools: " + ", ".join(sorted(discovered_tools)))
        missing = EXPECTED_TOOLS - discovered_tools
        if missing:
            failed += 1
            print("FAIL: Missing tools: " + ", ".join(sorted(missing)))
        else:
            passed += 1
            print("PASS: All 11 required tools are registered")

    resources_list = record("Resources discovery", lambda: client.rpc("resources/list"))
    if resources_list is not None:
        resource_uris = {
            item.get("uri")
            for item in resources_list.get("resources", [])
            if isinstance(item, dict) and isinstance(item.get("uri"), str)
        }
        print("Discovered resources: " + ", ".join(sorted(resource_uris)))
        if "linux://system/summary" in resource_uris:
            passed += 1
        else:
            failed += 1
            print("FAIL: Required resource linux://system/summary was not advertised")

    prompts_list = record("Prompts discovery", lambda: client.rpc("prompts/list"))
    if prompts_list is not None:
        prompt_names = {
            item.get("name")
            for item in prompts_list.get("prompts", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        print("Discovered prompts: " + ", ".join(sorted(prompt_names)))
        if "health_check" in prompt_names:
            passed += 1
        else:
            failed += 1
            print("FAIL: Required prompt health_check was not advertised")

    calls = [
        ("get_system_metrics", {}),
        ("get_swap_usage", {}),
        ("get_disk_usage", {}),
        ("get_filesystem_inode_usage", {}),
        ("list_processes", {"limit": 5, "sort_by": "cpu"}),
        ("read_allowed_log", {"alias": "ssh", "lines": 5}),
        ("get_network_stats", {}),
        ("get_resource_pressure", {}),
        ("get_service_status", {"unit": "ssh.service"}),
        ("check_port", {"port": 3002}),
        ("get_system_alerts", {}),
    ]
    for name, arguments in calls:
        if name not in discovered_tools:
            failed += 1
            print(f"\n--- Tool call: {name} ---\nSKIP: tool was not advertised")
            continue

        raw_result = record(
            f"Tool call: {name}",
            lambda name=name, arguments=arguments: client.rpc(
                "tools/call", {"name": name, "arguments": arguments}
            ),
        )
        if raw_result is not None:
            try:
                print_value(result_value(raw_result), max_chars=2500)
            except DemoError as exc:
                # A tool-level MCP error is a failed tool execution, not a successful call.
                passed -= 1
                failed += 1
                print(f"FAIL: {exc}")

    resource_result = record(
        "Resource read: linux://system/summary",
        lambda: client.rpc(
            "resources/read", {"uri": "linux://system/summary"}
        ),
    )
    if resource_result is not None:
        contents = resource_result.get("contents", [])
        if contents:
            for item in contents:
                if isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        try:
                            print_value(json.loads(text_value), max_chars=2500)
                        except json.JSONDecodeError:
                            print_value(text_value, max_chars=2500)
        else:
            print_value(resource_result)

    prompt_result = record(
        "Prompt get: health_check",
        lambda: client.rpc(
            "prompts/get", {"name": "health_check", "arguments": {"focus": "overview"}}
        ),
    )
    if prompt_result is not None:
        messages = prompt_result.get("messages", [])
        if messages:
            for message in messages:
                if isinstance(message, dict):
                    print(extract_text(message.get("content", "")))
        else:
            print_value(prompt_result)

    return passed, failed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call the deployed Linux MCP server through Caddy using a Keycloak token."
    )
    parser.add_argument(
        "--env-file",
        default=str(Path.home() / ".config/linux-mcp-agent/keycloak-clients.env"),
        help="File containing MCP_AGENT_CLIENT_ID and MCP_AGENT_CLIENT_SECRET.",
    )
    parser.add_argument("--endpoint", help="Override the MCP Streamable HTTP endpoint.")
    parser.add_argument("--token-url", help="Override the Keycloak token endpoint.")
    parser.add_argument("--resource", help="Override the OAuth resource indicator.")
    parser.add_argument(
        "--ca-cert",
        help="Caddy root CA certificate in PEM format (overrides automatic discovery).",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file).expanduser())

    issuer = os.getenv("MCP_DEMO_ISSUER_URL", DEFAULT_ISSUER).rstrip("/")
    resource = args.resource or os.getenv("MCP_DEMO_RESOURCE_URI", DEFAULT_RESOURCE)
    endpoint = args.endpoint or os.getenv("MCP_DEMO_ENDPOINT", DEFAULT_ENDPOINT)
    token_url = args.token_url or os.getenv(
        "MCP_DEMO_TOKEN_URL",
        f"{issuer}/protocol/openid-connect/token",
    )
    if args.timeout <= 0:
        print("ERROR: --timeout must be greater than zero", file=sys.stderr)
        return 2

    try:
        opener, tls_source = make_opener(
            args.ca_cert,
            Path(__file__).resolve().parents[1],
        )
        print("Linux MCP Agent Server — live acceptance demo")
        print(f"MCP endpoint: {endpoint}")
        print(f"Keycloak issuer: {issuer}")
        print(f"Resource indicator: {resource}")
        print(f"TLS verification: enabled ({tls_source})")
        print("\n--- Keycloak client credentials flow ---")
        token, granted_scope = request_access_token(
            opener,
            token_url=token_url,
            resource=resource,
            timeout=args.timeout,
        )
        print("PASS: Keycloak issued an access token (token value hidden)")
        print(f"Granted scope: {granted_scope}")

        client = StreamableHttpMcpClient(
            opener,
            endpoint=endpoint,
            token=token,
            timeout=args.timeout,
        )
        passed, failed = run_acceptance_demo(client)
    except DemoError as exc:
        print(f"\nFATAL: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nDemo interrupted.", file=sys.stderr)
        return 130

    print("\n" + "=" * 56)
    print(f"MCP LIVE ACCEPTANCE: {'PASS' if failed == 0 else 'FAIL'}")
    print(f"Checks passed: {passed} | checks failed: {failed}")
    print("The access token was kept in memory and was not printed or saved.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
