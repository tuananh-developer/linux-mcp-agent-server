# ADR-0001: Retain Python and the official MCP Python SDK

- **Status:** Accepted for the current project release.
- **Decision date:** 2026-11-17.

## Context

The project already has a working MCP Core, Linux telemetry collectors, configuration, tests and an implementation of the security/infrastructure workstream in Python. The primary target is one Ubuntu 24.04 LTS x86_64 host. Most operations are bounded operating-system reads, process sampling and network I/O to Keycloak.

## Decision

Retain Python 3.15.2 and the official MCP Python SDK 2.3.0 for this release. Keep the code split between MCP composition, configuration, token validation, journald reading and Linux telemetry.

Do not rewrite the server in Rust as part of finalization. Evaluate a language/runtime change only after the acceptance benchmark identifies a measurable bottleneck that Python cannot meet within the current NFRs.

## Consequences

- The existing implementation, team knowledge and tests remain usable.
- Python remains suitable for psutil, subprocess management, Starlette/Uvicorn and the official MCP SDK.
- The team avoids introducing a second runtime, new deployment process and cross-language integration before demonstrating a need.
- Runtime performance must be measured on the Ubuntu acceptance host; no performance claim follows from this decision alone.
