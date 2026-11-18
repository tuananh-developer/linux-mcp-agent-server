# Live MCP demo runbook

This runbook demonstrates the deployed MCP server itself: Keycloak client-credentials authentication, Streamable HTTP initialization, all four read-only tools, the system summary resource, and the health-check prompt. It does not invoke an LLM or claim to demonstrate an external Agent runtime.

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

The client obtains a short-lived Keycloak token using the resource indicator https://mcp.home.arpa/mcp, then performs the following live requests:

1. MCP initialize and notifications/initialized.
2. tools/list, then calls get_system_metrics, get_disk_usage, list_processes, and read_allowed_log.
3. resources/list and resources/read for linux://system/summary.
4. prompts/list and prompts/get for health_check.

The access token is held in memory only. The script does not print or save the token or client secret.

## TLS certificate note

TLS verification is enabled by default. Install the Caddy local root CA on the machine running the demo client, or pass its PEM path:

    uv run python scripts/demo_live.py --ca-cert /path/to/caddy-local-root.crt

For a temporary demo on an isolated local VM only, --insecure disables certificate verification:

    uv run python scripts/demo_live.py --insecure

Do not use --insecure for a production client or an untrusted network.

## Expected result

The terminal ends with:

    MCP LIVE ACCEPTANCE: PASS
    Checks passed: ... | checks failed: 0

The script exits non-zero if token issuance, MCP initialization, a required tool, the resource, or the prompt fails. A successful run proves the live Keycloak-to-MCP integration and the read-only MCP contract. It does not prove AI model inference or autonomous agent behavior.
