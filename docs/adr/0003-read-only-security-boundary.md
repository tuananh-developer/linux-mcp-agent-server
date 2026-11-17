# ADR-0003: Enforce a read-only server-side security boundary

- **Status:** Accepted.
- **Decision date:** 2026-11-17.

## Context

The server exposes host telemetry to an external Agent/MCP Client. Tool output, including journal messages, is untrusted. A model or client may request unsafe operations or attempt to inject command/path values.

## Decision

Expose only read-only, narrowly scoped Tools. Use administrator-owned disk paths and journal aliases. Construct journalctl arguments on the server and run with `shell=False`; bound execution time, line count and output bytes; redact common secrets. Exclude process command lines and environment variables. Require a valid OAuth access token for production requests and a separate log scope for journal access.

MCP read-only annotations, if added later, are client-facing metadata only; they do not replace authorization, allowlists or server-side validation.

## Consequences

- Tool names and schemas remain intentionally narrow.
- Arbitrary shell, file mutation, process kill and service restart are out of scope.
- The systemd journal group remains a documented residual privilege because it can expose more host journal data than the application aliases.
- Security regression tests must verify that denied requests do not invoke the underlying operating-system reader.
