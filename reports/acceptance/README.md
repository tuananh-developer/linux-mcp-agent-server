# Acceptance evidence

This directory stores evidence produced by the designated Ubuntu 24.04 LTS x86_64 acceptance host. Do not commit access tokens, client secrets, database dumps, Caddy CA private keys, raw journal content or personal data.

## Required evidence

| Gate | Evidence to record | Owner |
|---|---|---|
| Core quality | GitHub Actions run for Python 3.14.10 and 3.15.2: Ruff, strict Pyright, pytest | Workstream 1 |
| MCP over HTTP | Official MCP Client connects to the deployed Streamable HTTP endpoint and discovers/calls Tools, Resource and Prompt | Workstream 3 |
| OAuth | Positive and negative token cases for active state, issuer, expiry, resource/audience and scopes | Workstreams 2 and 3 |
| Log security | Alias allowlist, missing log scope, command boundary, timeout, output cap and redaction | Workstreams 2 and 3 |
| TLS/LAN | Trusted HTTPS from a second device; approved routes work; Keycloak administration and unlisted paths are blocked | Workstreams 2 and 3 |
| Deployment | Compose health, PostgreSQL persistence, loopback-only ports, non-root systemd identity and sandbox | Workstreams 2 and 3 |
| Performance | Per-tool sample count and p50/p95/p99 on Ubuntu 24.04 with CPU/RAM/OS/Python/SDK details | Workstream 3 |

## Recording format

For each gate, record:
- UTC date/time and the tested commit SHA.
- Ubuntu release, kernel, architecture, CPU and RAM.
- Python, MCP SDK, Docker/Compose and service image versions where relevant.
- Exact commands or test invocation.
- Actual output, pass/fail result and any raw machine-readable report.
- Known limitations, skipped checks and follow-up owner.

Use `scripts/benchmark_mcp.py` to produce JSON latency measurements:

```bash
MCP_BENCHMARK_URL=https://mcp.home.arpa/mcp \
MCP_BENCHMARK_ACCESS_TOKEN='<read token from a protected secret source>' \
MCP_BENCHMARK_LOG_ALIAS=ssh \
uv run python scripts/benchmark_mcp.py --iterations 100 \
  --output reports/acceptance/benchmark-ubuntu2404.json
```

The script does not write the bearer token or tool output into the report.

## Current status

No live Ubuntu 24.04 / second-device acceptance result is pre-populated in this repository. Automated tests, configuration validation and source review must not be presented as proof of live deployment acceptance. Add evidence only after the check has actually been executed.
