# OOAD analysis and UML

## Analysis approach

The implementation is a modular Python application with a function-oriented Linux telemetry core and a small number of stateful boundary objects. The design follows separation of concerns rather than introducing service classes that do not exist in the source code.

The MCP SDK owns protocol framing, schema publication and request dispatch. The application registers handlers in server.py; operating-system collection is implemented by functions in system.py and log_reader.py; configuration is represented by the immutable Settings dataclass; OAuth introspection is implemented by KeycloakIntrospectionVerifier.

## Module responsibilities

| Module | Main responsibility | Important elements |
|---|---|---|
| config.py | Parse and validate runtime settings and security invariants. | `Settings`, `ConfigurationError` |
| server.py | Compose the MCP server and register tools, resource, prompt and health route. | `build_mcp_server`, `build_asgi_app` |
| auth.py | Adapt Keycloak RFC 7662 introspection to the MCP SDK token-verifier interface. | `KeycloakIntrospectionVerifier` |
| auth_claims.py | Pure validation and normalization of introspection claims. | `validate_introspection_payload` |
| system.py | Read CPU, memory, disk and process snapshots. | `get_system_metrics`, `get_disk_usage`, `list_processes`, `system_summary` |
| log_reader.py | Resolve configured journal aliases and perform bounded, redacted reads. | `load_log_sources`, `read_allowed_log`, `run_journalctl_bounded` |
| __main__.py | Configure logging and start the ASGI application with Uvicorn. | `main` |

## Domain and boundary objects

- `Settings` is a frozen, slotted dataclass containing validated configuration. It prevents accidental mutation of security-sensitive settings after startup.
- `KeycloakIntrospectionVerifier` implements the MCP SDK `TokenVerifier` contract. It rejects inactive or malformed introspection responses and produces an SDK `AccessToken` only after the configured claim checks pass.
- `MCPServer` is an object supplied by the official MCP SDK. `build_mcp_server` creates it and registers application handlers; the repository does not define a separate `LinuxMCPServer` class.
- `Starlette` hosts the MCP sub-application and the unauthenticated operational `/healthz` route. Its lifespan owns the MCP session manager because the MCP application is mounted inside a parent ASGI application.
- `NotAllowedError` and `LogReadError` are narrow domain exceptions used to report rejected filesystem requests and safe journal-reader failures.

## Design principles

- **Single responsibility:** protocol registration, authentication, telemetry, journal access and configuration are separated by module.
- **Dependency direction:** Linux reader functions do not depend on MCP or OAuth. `server.py` is the composition layer that connects the MCP SDK to those functions.
- **Least privilege:** disk paths and journal aliases come from administrator-controlled configuration; the caller cannot provide a shell command, executable, raw unit or arbitrary filesystem path.
- **Fail closed:** invalid configuration or an invalid token must not result in unauthenticated or broader access.
- **Bounded work:** process sampling, journal line count, journal execution time and journal output size are bounded.
- **Untrusted output:** log messages are data, not instructions; the external Agent must not execute instructions found inside logs.

## Use-case analysis

### UC-01 — Request a Linux health overview

**Primary actor:** End user through an external Agent/MCP Client.

**Preconditions:** The MCP server is running. In production, the client has a valid token with the base `mcp.read` scope.

**Main flow:**
1. The client initializes an MCP session and discovers available tools.
2. The Agent selects the tools needed for the requested overview.
3. The client invokes `get_system_metrics`, `get_disk_usage` and, when useful, `list_processes`.
4. The server validates arguments and reads only permitted host telemetry.
5. The server returns structured results with timestamps and status fields.
6. The Agent summarizes the returned measurements for the user.

**Alternative flow:** If a process exits or is inaccessible during sampling, the server omits that entry, increments the inaccessible/exited count and returns `partial` status instead of combining data from different process identities.

### UC-02 — Read an allowlisted system log

**Primary actor:** External Agent/MCP Client.

**Preconditions:** The alias exists in the server-side log-source configuration. In production, the token has both `mcp.read` and `mcp.logs.read`.

**Main flow:**
1. The client invokes `read_allowed_log` with an alias and bounded line count.
2. The server checks the additional log scope.
3. The reader maps the alias to a fixed systemd unit.
4. The reader invokes the fixed `journalctl` executable with `shell=False`.
5. The reader enforces execution and output limits, parses entries and redacts common secret patterns.
6. The server returns structured log entries and truncation status.

**Alternative flow:** Unknown aliases, missing scope, timeout, malformed configuration or journal access errors are rejected without running an arbitrary command.

### UC-03 — Read contextual system information

**Primary actor:** External Agent/MCP Client.

**Preconditions:** The client is connected and authorized.

**Main flow:** The client discovers `linux://system/summary`, reads it, and receives a JSON snapshot. The client may obtain the `health_check` prompt with a supported focus value to guide the analysis.

## Sequence diagram — authenticated tool call

``` mermaid
sequenceDiagram
  participant U as User
  participant A as Agent / MCP Client
  participant C as Caddy
  participant M as MCP Server
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

## Class diagram — objects actually defined or instantiated by the application

``` mermaid
classDiagram
  class Settings {
    +str app_env
    +str auth_mode
    +str host
    +int port
    +tuple allowed_disk_paths
    +from_env()
  }
  class TokenVerifier {
    <<MCP SDK interface>>
    +verify_token(token)
  }
  class KeycloakIntrospectionVerifier {
    -Settings settings
    +verify_token(token)
  }
  class MCPServer {
    <<MCP SDK>>
    +tool()
    +resource()
    +prompt()
    +streamable_http_app()
  }
  class Starlette {
    <<ASGI framework>>
    +routes
    +lifespan
  }
  class NotAllowedError
  class LogReadError

  TokenVerifier <|.. KeycloakIntrospectionVerifier
  MCPServer ..> Settings : handlers capture validated settings
  MCPServer ..> KeycloakIntrospectionVerifier : production auth mode
  Starlette o-- MCPServer : mounts MCP ASGI app
```

## Traceability

- FR-001, FR-008, FR-009 and FR-010 are implemented by `server.py` and the MCP SDK composition.
- FR-002 through FR-005 are implemented by `system.py`.
- FR-006 and FR-007 are implemented by `log_reader.py`.
- Authentication and claim validation are implemented by `auth.py` and `auth_claims.py`.
- Unit and in-process MCP Client contract tests are located under `tests/`; real TLS/OAuth/LAN acceptance remains a deployment activity, not a unit-test claim.
