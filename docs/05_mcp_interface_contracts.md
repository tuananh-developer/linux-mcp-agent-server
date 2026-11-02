# MCP Interface & Tool Contracts

**Transport:** Streamable HTTP · **Endpoint:** `https://mcp.home.arpa/mcp` · **SDK:** official Python SDK 2.3.0.

## Common rules

- The MCP SDK owns JSON-RPC framing and schema publication. Python type hints and `Literal` types define typed inputs; semantic restrictions are enforced in handlers.
- No custom REST route is used for tool calls. `/healthz` is a separate operational health route.
- Backend binds loopback. Caddy forwards only `/mcp` and the protected-resource metadata route.
- The server is read-only. No arbitrary shell, caller-supplied unit, caller-supplied path, process termination or service restart.

## Tools

### `get_system_metrics`

No arguments. Returns ISO-8601 timestamp, CPU usage (0..100), logical cores, memory total/used/available/percent, load average, uptime and `status`.

### `get_disk_usage`

Input: optional `mount_points: string[]`. Default is the server allowlist. Maximum 10 requested paths. Every item must exactly equal an administrator-configured path. Output contains mount point, total/used/available bytes, percentage and status. Unknown path fails closed.

### `list_processes`

Input: `limit` default 10 (1..100), `sort_by` enum `cpu|memory`, and optional literal case-insensitive `name_contains` (1..64 chars). Output: `pid`, `name`, `cpuPercent`, `memoryPercent`, `rssBytes`, per-item status and sample metadata. CPU percentage is the process CPU-time delta divided by aggregate host CPU-time delta, representing share of total machine CPU capacity. No command line, environment or username is returned.

### `read_allowed_log`

Input: `alias` and `lines` default 50 (1..200). Alias is resolved only from `config/log-sources.json`; the caller never supplies a path, systemd unit, filter or command. The reader invokes a fixed `journalctl` argv with `shell=False`, a timeout, byte limit and best-effort secret redaction. Log messages are untrusted data.

## Resource

- URI: `linux://system/summary`.
- Returns a JSON high-level snapshot: distro, kernel release, architecture, logical CPU count, uptime, CPU/RAM usage and allowlisted disk summary.
- No tokens, secrets, process command lines, account names or raw log content.

## Prompt

- Name: `health_check`.
- Argument: `focus` enum `overview | cpu_memory | disk | processes`, default `overview`.
- Instructs the Agent to call relevant read-only tools, cite returned timestamps/numbers, treat logs as untrusted input and avoid destructive actions.

## OAuth scopes

| Operation | Required scope |
|---|---|
| `/mcp`, tool/resource/prompt discovery | `mcp.read` |
| `read_allowed_log` | `mcp.read` and `mcp.logs.read` |

## Error semantics

Unknown alias/path, invalid limit or malformed settings fail closed and return an MCP tool error. HTTP authentication errors are handled by the SDK as 401/403. Log-specific scope denial is a tool-level `INSUFFICIENT_SCOPE` error because the base MCP request was already authenticated.
