# Security threat model

## Assets and trust boundaries

Assets: system telemetry, journal content, OAuth tokens and client secrets, Keycloak signing keys, Caddy internal CA private key, MCP configuration. Boundaries: Agent/Client to LAN reverse proxy; Caddy to loopback services; MCP process to Linux kernel/filesystem/journald; systemd manager to service identity.

## Required controls

- Non-root service account; systemd sandboxing; backend and Keycloak bind to loopback; PostgreSQL private Docker network.
- Only Caddy TCP 443 is reachable from LAN. Caddy has exact host/path allowlists; Keycloak admin UI/API is local-only.
- TLS chain must be trusted by clients. Caddy internal CA root certificate may be distributed, but its private key must never leave the server.
- OAuth access tokens are introspected through the private loopback Keycloak listener; validate `active`, exact `iss`, mandatory `exp`, optional `nbf`, exact MCP `aud`/resource and base scope `mcp.read`. The authorization server validates its own token signatures before returning an active introspection response.
- Log tool additionally requires `mcp.logs.read`; no tokens/secrets in logs.
- Logs are untrusted data; output size, lines and timeout are bounded, and common credential patterns are redacted. Do not send raw logs to a remote LLM.
- No arbitrary shell execution. `journalctl` receives server-owned argv with `shell=False`; paths and units are server allowlisted.
- Input limits and error messages avoid leaking internal host details.

## STRIDE summary

| Threat | Control | Evidence |
|---|---|---|
| Spoofing | TLS + OAuth issuer/audience/scope validation | Auth integration tests |
| Tampering | HTTPS + SDK schema validation + allowlists | Input and TLS tests |
| Repudiation | Minimal structured logs with non-secret client ID | Audit review |
| Information disclosure | Bounded allowlisted logs, no command line/env, secret redaction | Log tests |
| Denial of service | Bounded line count, byte output, process sampling, journal timeout | Performance tests |
| Elevation of privilege | Non-root, read-only tools, no shell interpolation, systemd hardening | Deployment inspection |

## Residual risks

Membership in `systemd-journal` can grant broader journal read access than the MCP aliases expose. Keycloak Resource Indicators is experimental in the pinned release. Caddy's internal CA root must be trusted by every client. LAN firewall rules must restrict exposure to the demo subnet/client IP. These risks are documented and must be considered in the final presentation.
