# Project charter and scope

## Objective

Build and configure a secure, read-only Linux MCP server that exposes system observability tools to an external Agent/MCP Client through the Model Context Protocol.

## In scope

- Official MCP Python SDK v2, Streamable HTTP `/mcp`.
- Linux CPU/RAM, allowlisted filesystem usage, bounded process list, allowlisted real systemd journal access.
- One MCP Resource and one MCP Prompt in addition to Tools.
- OAuth2/OIDC resource-server validation using Keycloak, exact issuer and resource/audience binding, scopes.
- Caddy HTTPS reverse proxy, PostgreSQL for Keycloak only, Docker Compose for infrastructure, native systemd service for the MCP process.
- Unit, integration, security and performance test plans.
- Ubuntu 24.04 LTS as primary acceptance environment; group of three.

## Out of scope

- LLM hosting, model inference, LangChain orchestration and provider fallback inside this repository.
- Arbitrary command execution, file writes/deletes, killing processes, restarting services.
- Public multi-tenant service, dashboard, application database, cloud deployment.
- Claiming distro portability without tests.

## Acceptance gates

1. Unit tests and quality tools pass.
2. MCP Inspector/compatible client discovers the tools, resource and prompt over Streamable HTTP.
3. Wrong issuer, expired token, wrong audience, missing base scope and missing log scope are rejected.
4. A second LAN device connects over trusted HTTPS; Caddy and Keycloak admin paths remain restricted.
5. systemd runs as a dedicated non-root user with journal access explicitly reviewed.
6. Tool benchmark records p95 <= 2 seconds on the acceptance host, excluding LLM inference.
