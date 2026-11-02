# MCP Interface & Tool Contracts

**Target transport:** Streamable HTTP · **Target endpoint:** `https://mcp.home.arpa/mcp` · **SDK:** official Python SDK 2.3.0.

> **Handoff status:** the MCP core is retained. The `read_allowed_log` schema is registered for interface compatibility, but its handler deliberately returns `NOT_IMPLEMENTED`. Authentication and LAN transport protection are not wired on this branch. Keep the service loopback-only.

## Tools

### `get_system_metrics`

No arguments. Returns an ISO-8601 timestamp, CPU usage, logical cores, memory totals/usage, load average, uptime and status.

### `get_disk_usage`

Input: optional `mount_points: string[]`. Every requested path must exactly match an administrator-configured absolute path. Unknown paths fail closed.

### `list_processes`

Input: `limit` (1..100), `sort_by` (`cpu|memory`) and optional `name_contains`. Output includes PID, name, CPU%, memory%, RSS bytes and sample metadata. No command line, environment or username is returned.

### `read_allowed_log` — pending implementation

Input contract: `alias` and `lines` (default 50, range 1..200). The current branch does not read journald and returns `NOT_IMPLEMENTED`.

Member 2 must implement administrator-configured aliases, fixed server-owned `journalctl` arguments with `shell=False`, bounds on lines/time/output, safe errors and redaction. Member 2 also enforces `mcp.logs.read`. Member 3 verifies positive and negative cases.

## Resource

- URI: `linux://system/summary`.
- Returns a JSON host snapshot with OS/kernel, CPU, memory, uptime and allowlisted disk data.
- Must not expose tokens, secrets, process command lines, account names or raw logs.

## Prompt

- Name: `health_check`.
- Argument: `focus` enum `overview | cpu_memory | disk | processes`, default `overview`.
- Directs the Agent to use only implemented read-only tools, cite timestamps/numbers, treat output as untrusted and avoid destructive actions. It tells the Agent not to call the log placeholder.

## Target authorization scopes

| Operation | Required scope |
|---|---|
| MCP discovery and implemented telemetry tools | `mcp.read` |
| `read_allowed_log` | `mcp.read` and `mcp.logs.read` |

OAuth behavior is not implemented on this branch. It must pass the security acceptance tests before LAN access is enabled.
