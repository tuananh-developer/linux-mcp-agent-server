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

### `get_network_stats`

Optional input: `interface`, an exact interface name (1..64 characters). With no argument, returns at most 64 interfaces. Output contains link state, MTU, speed and cumulative byte/packet/error/drop counters. Interface addresses are intentionally omitted; counters are cumulative and must not be presented as a measured rate.

### `get_service_status`

Input: exact `unit` name. Only administrator-configured `ALLOWED_SYSTEMD_UNITS` entries ending in `.service` are accepted. The implementation invokes a fixed `systemctl show` argv with `shell=False`, a two-second timeout and a strict property list. It never accepts a command, unit path, or action from the caller. This tool only reads state.

### `check_port`

Input: one integer TCP port (1..65535). It attempts one connection to `127.0.0.1` with a bounded timeout. No host argument, remote destination, port range or UDP scan is supported.

### `get_system_alerts`

No arguments. Evaluates CPU, memory and configured filesystem usage against administrator-set warning thresholds. Defaults are CPU 85%, memory 90% and disk 85%; values are configurable through `CPU_WARNING_THRESHOLD_PERCENT`, `MEMORY_WARNING_THRESHOLD_PERCENT` and `DISK_WARNING_THRESHOLD_PERCENT`. It returns explainable threshold findings, not predictive diagnosis or automated remediation.

## Resource

- URI: `linux://system/summary`.
- Returns a JSON high-level snapshot: distro, kernel release, architecture, logical CPU count, uptime, CPU/RAM usage, allowlisted disk summary and per-interface network counters. Interface addresses and raw logs are excluded.
- No tokens, secrets, process command lines, account names or raw log content.

## Prompt

- Name: `health_check`.
- Argument: `focus` enum `overview | cpu_memory | disk | processes | network | services | alerts`, default `overview`.
- Instructs the Agent to call relevant read-only tools, cite returned timestamps/numbers, treat logs as untrusted input and avoid destructive actions.

## OAuth scopes

| Operation | Required scope |
|---|---|
| `/mcp`, tool/resource/prompt discovery | `mcp.read` |
| `read_allowed_log` | `mcp.read` and `mcp.logs.read` |
| Other four monitoring/diagnostic tools | `mcp.read` |

## Error semantics

Unknown alias/path, invalid limit or malformed settings fail closed and return an MCP tool error. HTTP authentication errors are handled by the SDK as 401/403. Log-specific scope denial is a tool-level `INSUFFICIENT_SCOPE` error because the base MCP request was already authenticated.
