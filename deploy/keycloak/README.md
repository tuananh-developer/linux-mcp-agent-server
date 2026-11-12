# Keycloak resource-server setup — implementation brief

> **Status on `team-handoff`:** requirements reference only. The Compose service and MCP OAuth implementation are absent from this branch. Member 2 owns implementation; member 3 verifies it with live positive/negative tests. This document is not proof of a running deployment.


Keycloak 26.8.1 is the Authorization Server. The MCP process is only a resource server: it introspects access tokens and does not issue them. The container enables the `resource-indicators` feature because MCP requires resource-bound access tokens in the current protocol line. Keycloak documents this feature as experimental, so the integration must be explicitly tested against the pinned image before a LAN demo.

## Realm and clients

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
