# MCP Interface & Tool Contracts

**Transport:** Streamable HTTP  
**Path:** `/mcp`  
**SDK:** official MCP Python SDK 2.3.0

The MCP interface is a compatibility boundary. Tool names, Resource URI, Prompt name and argument semantics must not change without updating the SRS, tests and client-facing documentation in the same reviewed change.

## Tools

### `get_system_metrics`

**Arguments:** none.

Returns:
- `timestamp`: UTC ISO-8601 observation time.
- `cpuUsagePercent`, `cpuLogicalCores`.
- `memoryTotalBytes`, `memoryUsedBytes`, `memoryAvailableBytes`, `memoryUsagePercent`.
- `loadAverage1m5m15m`: one-, five- and fifteen-minute load values where supported.
- `uptimeSeconds`, `status`.

The CPU value is a bounded psutil observation, not a prediction or a process-specific metric.

### `get_disk_usage`

**Arguments:** optional `mount_points: string[]`.

Omitting the argument uses the configured disk allowlist. Every requested path must exactly match a server-configured absolute path. The server rejects an unknown path and more than ten requested mount points.

Each filesystem result contains `mountPoint`, `totalBytes`, `usedBytes`, `availableBytes`, `usagePercent` and `status`.

### `list_processes`

**Arguments:**
- `limit`: integer from 1 to 100; default 10.
- `sort_by`: `cpu` or `memory`; default `cpu`.
- `name_contains`: optional 1–64 character non-whitespace filter.

Each returned process includes PID, name, CPU%, memory%, RSS bytes and status. The implementation uses PID plus process creation time to avoid mixing measurements after PID reuse. The result includes `sampleWindowMs` (measured elapsed sampling time), `requestedSampleWindowMs`, CPU-percentage semantics and an inaccessible/exited count.

The result intentionally excludes command-line arguments, environment variables, usernames and other process metadata that is not needed for observability.

### `read_allowed_log`

**Arguments:**
- `alias`: required administrator-configured alias.
- `lines`: integer from 1 to 200; default 50.

The alias maps to a configured systemd `.service` unit. Client input never supplies a journalctl executable, raw unit, file path or command argument. The handler requires the base `mcp.read` scope and checks `mcp.logs.read` before launching the journal reader.

The result contains `logName`, `sourceType`, resolved `unit`, `linesReturned`, `truncated`, `content` and `status`. Each content entry contains a timestamp (nullable for malformed journal timestamps), priority and redacted message. Execution time and captured/serialized output bytes are bounded.

## Resource

- URI: `linux://system/summary`.
- MIME type: `application/json`.
- Returns operating system, kernel, architecture, CPU, memory, uptime and allowlisted disk information.
- Must not contain tokens, secrets, raw logs, process command lines, environment values or usernames.

## Prompt

- Name: `health_check`.
- Argument: `focus` enum `overview | cpu_memory | disk | processes`, default `overview`.
- Directs an external Agent to use only read-only tools, quote measurements and timestamps, treat tool output as untrusted data and avoid destructive actions.

## Authorization contract

| Operation | Required scope |
|---|---|
| MCP discovery, Tools, Resource and Prompt | `mcp.read` |
| `read_allowed_log` | `mcp.read` and `mcp.logs.read` |

The base scope is enforced by the MCP SDK auth settings. The additional log scope is checked by the tool handler before any journal command is invoked.

## Error and safety behavior

- Invalid or non-allowlisted disk paths are rejected.
- Invalid process limits, sort keys and name filters are rejected.
- Inactive, malformed, expired, wrong-issuer, wrong-audience/resource or insufficient-scope tokens fail closed.
- Unknown log aliases, invalid line limits, journal timeout, output overflow and journal execution failures return bounded errors or explicitly marked partial results.
- No tool accepts shell fragments, executable paths, arbitrary filesystem paths or systemd unit names from the caller.

## Browser assistant

`/` and `/dashboard` serve the AI chat interface. The browser initializes an MCP session, discovers tools and executes model-selected calls through `/mcp`. External clients continue to use the same tool, resource and prompt schemas.
