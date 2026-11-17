# OOAD analysis and UML

## Design overview

The application separates MCP protocol composition, environment configuration, identity validation, journal access and Linux telemetry. Infrastructure services are deployed independently from the Python MCP process.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `config.py` | Immutable environment settings, URL/resource validation, loopback constraints and execution bounds |
| `server.py` | MCP composition, Tools, Resource, Prompt, auth wiring and ASGI lifecycle |
| `system.py` | CPU, memory, load, uptime, disk, process and host-summary collectors |
| `auth.py` | Async token-verifier adapter for Keycloak introspection |
| `auth_claims.py` | Pure validation of introspection claims |
| `log_reader.py` | Alias mapping, fixed journalctl arguments, time/output caps and redaction |
| `__main__.py` | Logging and Uvicorn startup |

## Main runtime sequence

```mermaid
sequenceDiagram
  participant Client as External MCP Client
  participant Caddy
  participant MCP as MCP Server
  participant Auth as Keycloak
  participant OS as Linux Host

  Client->>Caddy: HTTPS MCP request + Bearer token
  Caddy->>MCP: Forward to loopback /mcp
  MCP->>Auth: RFC 7662 token introspection
  Auth-->>MCP: active, iss, exp, aud, scope
  Note over MCP: Validate mcp.read and resource binding
  alt read_allowed_log
    MCP->>MCP: Require mcp.logs.read
    MCP->>OS: journalctl with server-owned argv
  else telemetry tool
    MCP->>OS: Read psutil/statvfs telemetry
  end
  OS-->>MCP: Bounded structured data
  MCP-->>Caddy: MCP result
  Caddy-->>Client: HTTPS response
```

## Class/module view

```mermaid
classDiagram
  class Settings {
    +str host
    +int port
    +str resource_uri
    +str required_audience
    +tuple allowed_disk_paths
    +from_env()
  }
  class KeycloakIntrospectionVerifier {
    +verify_token(token)
    -_verify_sync(token)
  }
  class AuthClaims {
    +validate_introspection_payload(payload)
  }
  class MCPServer {
    <<MCP SDK>>
    +tool()
    +resource()
    +prompt()
    +streamable_http_app()
  }
  class LinuxTelemetry {
    +get_system_metrics()
    +get_disk_usage()
    +list_processes()
    +system_summary()
  }
  class JournalReader {
    +load_log_sources()
    +read_allowed_log()
    +run_journalctl_bounded()
  }
  class Starlette {
    <<ASGI host>>
    +lifespan
    +healthz
  }
  Settings --> KeycloakIntrospectionVerifier
  KeycloakIntrospectionVerifier --> AuthClaims
  MCPServer --> LinuxTelemetry
  MCPServer --> JournalReader
  Starlette o-- MCPServer
```

## Security and object constraints

- The configuration object is immutable after construction.
- Token validation rejects malformed or non-finite NumericDate claims rather than allowing them to raise during request authentication.
- Process identity is checked using PID plus creation time to avoid mixing samples after PID reuse.
- Journal aliases map to configured `.service` units; caller input is never interpolated into a shell command.
- The journal reader uses `shell=False`, bounded lines, execution timeout, byte limit and best-effort redaction.
- PostgreSQL belongs to the Keycloak persistence boundary, not the application data model.
