# Keycloak resource-server setup

Keycloak 26.8.1 is the Authorization Server. The MCP process is only a resource server: it introspects access tokens and does not issue them. The container enables the `resource-indicators` feature because MCP requires resource-bound access tokens in the current protocol line. Keycloak documents this feature as experimental, so the integration must be explicitly tested against the pinned image before a LAN demo.

## Option A: Fast import using `realm-linux-agent.example.json`

A pre-configured realm template is provided at `deploy/keycloak/realm-linux-agent.example.json` containing:
- Realm `linux-agent` (`sslRequired: external`, 300s access token lifespan).
- Client scopes `mcp.read` and `mcp.logs.read` (`include.in.token.scope=true`).
- Confidential introspection client `linux-mcp-resource-server` with `resource_url=https://mcp.home.arpa/mcp`.
- Confidential machine client `linux-mcp-agent-client` with service account enabled and an audience mapper binding `https://mcp.home.arpa/mcp` into both the access token and token introspection response.

Steps:
1. Copy `deploy/keycloak/realm-linux-agent.example.json` to an ignored local file (e.g. `/tmp/realm-linux-agent.json`) and replace `CHANGE_ME_RESOURCE_SERVER_SECRET` and `CHANGE_ME_AGENT_CLIENT_SECRET` with strong random secrets (`openssl rand -base64 32`).
2. Import the file from the local Keycloak Admin Console (`http://127.0.0.1:8080/admin/` -> **Create Realm** -> **Browse** `/tmp/realm-linux-agent.json` -> **Create**), then delete `/tmp/realm-linux-agent.json`.
3. Copy the `linux-mcp-resource-server` secret into `/etc/linux-mcp-agent/server.env` as `MCP_INTROSPECTION_CLIENT_SECRET`.

## Option B: Manual realm and client creation

Create a realm named `linux-agent` from the local Keycloak admin console (`https://auth.home.arpa/admin/`). The admin route is intentionally blocked from other LAN hosts.

Create a confidential client `linux-mcp-resource-server` with service accounts enabled and client authentication enabled. It is used only by the MCP service to authenticate to the introspection endpoint. Store its secret in `/etc/linux-mcp-agent/server.env` as `MCP_INTROSPECTION_CLIENT_SECRET`.

Configure the MCP server client/resource:

- Client ID: `linux-mcp-resource-server`.
- Client attribute `resource_url`: `https://mcp.home.arpa/mcp`.
- Ensure the `resource-indicators` feature is enabled on the running Keycloak server.

Create a machine client for the Agent/MCP Client (for example `linux-mcp-agent-client`) with service accounts enabled. Give it the scopes `mcp.read` and, only when log access is required, `mcp.logs.read`. Bind the MCP resource URI to the access token audience using the Resource Indicator flow. Client credentials must include both `scope` and `resource=https://mcp.home.arpa/mcp`.

## Token and introspection checks

The MCP server calls the loopback-only `MCP_INTROSPECTION_URL` (default `http://127.0.0.1:8080/realms/linux-agent/protocol/openid-connect/token/introspect`) and rejects inactive tokens, missing/expired `exp`, future `nbf`, wrong `iss`, wrong `aud`, missing `mcp.read`, and tokens without a client ID. The SDK additionally enforces the resource value and base scope. `read_allowed_log` checks `mcp.logs.read` inside the tool. No token or secret is written to application logs.

Keycloak Resource Indicators and the latest MCP protocol revision are documented as experimental in Keycloak 26.8.1. Until tests prove correct `resource` -> `aud` behavior and introspection claims on the target realm, keep LAN access closed. Do not bypass the audience check to make a demo work.
