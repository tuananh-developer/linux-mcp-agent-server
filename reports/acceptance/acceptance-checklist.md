# Ubuntu 24.04 acceptance checklist

Record the commit SHA, date/time, environment, commands, output and result for every item. An unchecked item is not accepted.

## CI and application

- [ ] Ruff passes on Python 3.14.10.
- [ ] Strict Pyright passes on Python 3.14.10.
- [ ] Pytest passes on Python 3.14.10.
- [ ] Ruff, strict Pyright and pytest pass on Python 3.15.2.
- [ ] Official MCP Client connects over TCP/Streamable HTTP and discovers four Tools, one Resource and one Prompt.
- [ ] Metrics, disk, process and allowed-log tools return the documented bounded contract.

## OAuth and security

- [ ] Active token with exact issuer, unexpired finite `exp`, canonical audience/resource and `mcp.read` succeeds.
- [ ] Inactive, malformed, expired, wrong-issuer, wrong-audience and missing-base-scope tokens fail closed.
- [ ] Missing `mcp.logs.read` does not invoke journalctl.
- [ ] Unknown aliases and invalid line limits are rejected.
- [ ] Journal timeout and output cap are enforced.
- [ ] Redaction tests cover bearer/basic credentials, secret fields and URL credentials.
- [ ] No arbitrary shell, process command line, process environment or destructive operation is exposed.

## Infrastructure and deployment

- [ ] PostgreSQL and Keycloak containers report healthy.
- [ ] Keycloak realm and client configuration are imported with generated secrets.
- [ ] PostgreSQL data survives a controlled container recreation.
- [ ] MCP and Keycloak application ports bind to loopback only.
- [ ] PostgreSQL and Keycloak management ports are not published.
- [ ] systemd runs as the dedicated non-root account with documented sandbox settings.
- [ ] Journal group residual privilege is reviewed and accepted or mitigated.
- [ ] Caddy certificate is trusted from a second LAN device.
- [ ] Authenticated Streamable HTTP works from that device.
- [ ] Keycloak admin and unlisted proxy paths are blocked from LAN.

## Performance and operational readiness

- [ ] Each exposed tool has repeatable p50/p95/p99 measurements.
- [ ] p95 is at or below 2 seconds per tool on the acceptance host, excluding external LLM inference.
- [ ] Benchmark environment and sample count are recorded.
- [ ] Backup and rollback procedures are demonstrated.
- [ ] Known limitations and residual risks are recorded.
