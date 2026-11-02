# OOAD analysis and UML

## Domain objects

- `Settings`: immutable runtime configuration and security invariants.
- `KeycloakIntrospectionVerifier`: validates bearer tokens with the authorization server.
- `SystemMetricsService`: CPU/RAM/load/uptime snapshot.
- `DiskUsageService`: exact-path allowlist and filesystem statistics.
- `ProcessListService`: bounded process sampling and percentage semantics.
- `JournalReader`: alias-to-unit mapping, fixed argv, timeout and redaction.
- `LinuxMCPServer`: registers tools, resource and prompt.

## Design principles

Single responsibility is applied at module boundaries. The MCP adapter does not contain OS collection logic. System functions do not know about OAuth or MCP. The log reader never accepts a unit or command from the client. Authentication is checked before MCP handlers execute; the higher-privilege log operation has an additional scope check.

## Sequence: tool call

```mermaid
sequenceDiagram
  participant U as User
  participant A as Agent / MCP Client
  participant C as Caddy
  participant M as Python MCP Server
  participant K as Keycloak
  participant L as Linux
  U->>A: Ask for system status
  A->>C: POST /mcp + Bearer token
  C->>M: HTTPS reverse proxy
  M->>K: Introspect access token
  K-->>M: active, iss, exp, aud, scope
  M->>M: Validate resource + mcp.read
  M->>L: Read psutil /proc metrics
  L-->>M: System snapshot
  M-->>A: MCP tool result
  A-->>U: Natural-language summary
```

## Class diagram

```mermaid
classDiagram
  class Settings
  class KeycloakIntrospectionVerifier
  class LinuxMCPServer
  class SystemMetricsService
  class DiskUsageService
  class ProcessListService
  class JournalReader
  LinuxMCPServer --> Settings
  LinuxMCPServer --> KeycloakIntrospectionVerifier
  LinuxMCPServer --> SystemMetricsService
  LinuxMCPServer --> DiskUsageService
  LinuxMCPServer --> ProcessListService
  LinuxMCPServer --> JournalReader
```
