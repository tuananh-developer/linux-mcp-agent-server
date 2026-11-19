# Linux Observatory browser dashboard

The browser dashboard is served at / and /dashboard; the optional AI assistant is served at /assistant.

## Data flow

- The browser creates a same-origin MCP Streamable HTTP client for /mcp.
- It discovers the MCP tool registry and requires all eight read-only tools before marking the dashboard connected.
- The overview periodically invokes get_system_metrics, get_disk_usage, list_processes, get_network_stats, get_system_alerts, get_service_status, and check_port.
- Recent journal access is separate and is only attempted after the user presses the log button. It still requires the server journal alias allowlist and the mcp.logs.read scope.
- The AI assistant is optional. Its model gateway supplies tool schemas from the same MCP server and executes model-selected calls through the same authenticated MCP endpoint. It is disabled by default in the example environment.

## Security boundaries

- The MCP bearer token is held in JavaScript memory only. It is not persisted to localStorage, cookies, or the backend.
- Browser requests are same-origin and carry the same bearer token to the MCP endpoint. The browser cannot choose an arbitrary host, shell command, remote port target, or filesystem path.
- The dashboard uses textContent for host-provided values and log output; it does not render process names or journal messages as HTML.
- The dashboard is read-only. It does not start/stop services, terminate processes, edit files, or issue remote scans.
- Network counters are cumulative byte counters, not calculated throughput rates.
- Service inspection remains constrained by ALLOWED_SYSTEMD_UNITS; a service that is not allowlisted is shown as unavailable.

## Run

Start the normal MCP and Caddy deployment, then open https://mcp.home.arpa/ in a browser that trusts the Caddy local CA. The assistant is at https://mcp.home.arpa/assistant.

In Keycloak mode, obtain an access token with the MCP resource and mcp.read scope, then use Cấu hình MCP to paste it. The token remains in the current tab only. A separate mcp.logs.read scope is required for the log panel.

The UI refreshes the overview every 15 seconds. Clicking Làm mới requests a new snapshot immediately. The dashboard does not persist telemetry or create a metrics history database; the line chart shows only the most recent samples held in that browser tab.