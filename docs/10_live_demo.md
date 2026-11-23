# Live MCP demo runbook

This runbook demonstrates the deployed MCP server itself: Keycloak client-credentials authentication, Streamable HTTP initialization, all eight read-only tools, the system summary resource, and the health-check prompt. It does not invoke an LLM or claim to demonstrate an external Agent runtime.

## 1. Prepare the local configuration once

The supporting infrastructure reads its secrets from deploy/compose/.env:

    cp deploy/compose/.env.example deploy/compose/.env
    chmod 600 deploy/compose/.env

Replace both CHANGE_ME values with different strong passwords before starting the stack.

The demo client reads the machine-client credentials from:

    ~/.config/linux-mcp-agent/keycloak-clients.env

The file must contain these variable names (the values are the client credentials created in the linux-agent Keycloak realm):

    MCP_AGENT_CLIENT_ID=linux-mcp-agent-client
    MCP_AGENT_CLIENT_SECRET=replace-with-the-agent-client-secret

Protect the file:

    chmod 600 ~/.config/linux-mcp-agent/keycloak-clients.env

Do not commit either .env file or paste its secrets into a terminal command that will be saved in shell history.

If the MCP service is not installed as a systemd service, create a readable server environment file once:

    mkdir -p ~/.config/linux-mcp-agent
    cp deploy/systemd/server.env.example ~/.config/linux-mcp-agent/server.env
    chmod 600 ~/.config/linux-mcp-agent/server.env

Edit ~/.config/linux-mcp-agent/server.env and set the real introspection client secret. For a repository-local run, set LOG_SOURCES_FILE to the absolute path of this repository's config/log-sources.example.json. Keep AUTH_MODE=keycloak, MCP_HOST=127.0.0.1, and MCP_PORT=3002.

## 2. Start the services

In terminal 1, from the repository root:

    bash scripts/start-demo.sh

The helper validates the Compose configuration, starts PostgreSQL and Keycloak, waits for Keycloak's health check, and starts Caddy's LAN profile. It then:
- reuses the MCP service if its local health endpoint is already responding;
- restarts the installed linux-mcp-agent systemd service when available; or
- launches uv run linux-mcp-agent in the foreground using ~/.config/linux-mcp-agent/server.env.

When the helper launches the app in the foreground, leave terminal 1 running during the demo.

## 3. Run the live acceptance client

Open terminal 2 at the repository root:

    uv run python scripts/demo_live.py

Ensure the configured ALLOWED_SYSTEMD_UNITS contains ssh.service (or adjust the demo call in scripts/demo_live.py to a unit you intentionally allow). The client obtains a short-lived Keycloak token using the resource indicator https://mcp.home.arpa/mcp, then performs the following live requests:

1. MCP initialize and notifications/initialized.
2. tools/list, then calls get_system_metrics, get_disk_usage, list_processes, read_allowed_log, get_network_stats, get_service_status, check_port, and get_system_alerts.
3. resources/list and resources/read for linux://system/summary (including network counters).
4. prompts/list and prompts/get for health_check (overview or the network, services and alerts focus).

The access token is held in memory only. The script does not print or save the token or client secret.

## TLS certificate note

TLS verification is always enabled. When the Caddy Compose service is running, the demo client automatically reads its local root CA from the Caddy container and uses it to validate both `mcp.home.arpa` and `auth.home.arpa`. It does not disable certificate verification.

If automatic discovery is unavailable, provide the PEM file explicitly:

    uv run python scripts/demo_live.py --ca-cert /path/to/caddy-local-root.crt

You can also set `MCP_DEMO_CA_CERT` to that PEM file path. The explicit CA file takes precedence over automatic discovery. The `--insecure` option is intentionally not supported.

## Expected result

The terminal ends with:

    MCP LIVE ACCEPTANCE: PASS
    Checks passed: ... | checks failed: 0

The script exits non-zero if token issuance, MCP initialization, a required tool, the resource, or the prompt fails. A successful run proves the live Keycloak-to-MCP integration and the read-only MCP contract. It does not prove AI model inference or autonomous agent behavior.
