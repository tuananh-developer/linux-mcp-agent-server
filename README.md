# Linux MCP Agent Server

A read-only Linux observability server that exposes host telemetry through the Model Context Protocol (MCP). The primary deployment and acceptance target is **Ubuntu 24.04 LTS x86_64**.

The MCP server supports external clients and includes an optional browser assistant. The assistant uses OpenAI or local Ollama for inference and executes model-selected tools through MCP.

## MCP capabilities

| Type | Name | Purpose |
|---|---|---|
| Tool | `get_system_metrics` | Timestamped CPU, memory, load average and uptime |
| Tool | `get_disk_usage` | Filesystem capacity for administrator-allowlisted mount points |
| Tool | `list_processes` | Bounded process snapshot without command lines or environment values |
| Tool | `read_allowed_log` | Bounded, redacted journald entries from configured service aliases |
| Resource | `linux://system/summary` | High-level JSON host summary |
| Prompt | `health_check` | Safe, read-only host health-check guidance |

The server is read-only. It does not expose arbitrary shell execution, arbitrary file reads, process termination, service restart or file mutation.

## Architecture

- **MCP application:** Python, official MCP Python SDK 2.3.0, Streamable HTTP at `/mcp`; runs natively under systemd and binds to `127.0.0.1:3002`.
- **Identity:** Keycloak 26.8.1 issues OAuth access tokens. The MCP application is a resource server and validates tokens using RFC 7662 introspection, exact issuer, expiry, resource/audience and scopes.
- **TLS ingress:** Caddy 2.11.7 terminates internal TLS and exposes only the approved MCP, assistant and OIDC routes to the LAN.
- **Persistence:** PostgreSQL 18.6 stores Keycloak identity/configuration data only. It is **not an application database**; the MCP telemetry service does not persist metrics.
- **Containers:** Docker Compose runs PostgreSQL, Keycloak and the optional LAN-facing Caddy service. The MCP process itself is not containerized.

## Local development

Use the Python version selected by `.python-version` and uv 0.13.8. CI checks Python 3.14 and 3.15.

```bash
uv python install
uv sync --all-groups
cp .env.example .env
set -a
source .env
set +a
uv run linux-mcp-agent
```

The development environment defaults to `AUTH_MODE=disabled` and loopback binding. It is for same-host development only. Do not expose this mode to a LAN or public network.

## AI web interface and MCP service

Start the Python application and open `http://localhost:3002/` (or `/dashboard`). Restart an existing process after updating this checkout. The only user interface is **AI Assistant**: ask questions, inspect model-selected tool results, manage conversations and configure the MCP connection.

Linux tools run as MCP service capabilities at `/mcp`; there are no manual metrics/process/log screens or tool playground. The UI initializes MCP and discovers the tool registry, then executes tools only when the agent selects them during a chat. Opening the UI does not automatically sample the host or make a paid inference request. Resources and prompts remain available to other standards-compliant MCP clients.

In Keycloak mode, use **Cấu hình kết nối** to enter a Bearer token. It remains in tab memory, is cleared on disconnect/reload, and is never a model input. Tool calls still require the normal MCP scopes, including the additional journal scope. Model-selected tool results are shown as expandable evidence inside the chat, not as separate tool interfaces.

The static application uses no external frontend assets or build process. Host/Origin checks remain enabled. Conversations are not stored by the application backend. See below for the active model provider and its data-sharing boundary.

Transport tests (Node.js 22+, development only):

```bash
node --test tests/dashboard_transport.test.mjs tests/agent_loop.test.mjs
```

The Python suite exercises MCP over the in-process ASGI HTTP transport and checks browser-origin/authentication boundaries. It does not establish production TLS, live provider quality, systemd or second-device LAN acceptance.

## AI Assistant: OpenAI API (default)

Set these server-side environment variables in the ignored `.env` file:

```dotenv
AGENT_ENABLED=true
AGENT_PROVIDER=openai
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-6-luna
OPENAI_MAX_OUTPUT_TOKENS=1024
```

Do not put the key in frontend source or paste it into the MCP Bearer-token field. API billing/model access is managed by your OpenAI API project. The key is used only by the backend against the fixed HTTPS Responses endpoint. It is excluded from settings representations, status JSON, model messages and application errors. Redirects are disabled.

Reload the environment and restart the MCP application. Open **AI Assistant**. Status only reports whether a key is configured; model access, credits and connectivity are verified on the first submitted question. Opening the UI does not trigger paid inference.

The model receives server-derived tool schemas and chooses calls; the browser executes them through authenticated `/mcp` and sends observations for the next step. The UI shows tool results and accumulated input/output token usage per turn. Conversations stay in tab memory. No synthetic answers or automatic switch to a more expensive model are used.

**Data boundary:** questions, conversation history and tool results are sent to OpenAI in API mode. Journal data requires the explicit log-sharing checkbox and its MCP scope. Changing log consent starts a fresh conversation to prevent resending prior log results. The adapter requests `store=false`; this does not replace the provider's data-retention policies. Keys/tokens are never model inputs.

Cost controls: 1024 output tokens per API response by default (configurable 256–4096), reasoning disabled, sequential tool calls, at most five model rounds / ten MCP calls per user turn, one concurrent generation per app process, bounded request and tool-result sizes. Token usage accumulates across rounds. These limits are not a monthly spending cap; configure billing controls in the API project. `AGENT_ENABLED=false` disables inference.

## Optional local Ollama

Set `AGENT_PROVIDER=ollama`, install Ollama and run `ollama pull qwen3:4b`. Defaults: `OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_MODEL=qwen3:4b`, `OLLAMA_CONTEXT_LENGTH=4096`. The local adapter accepts loopback HTTP origins only. See `deploy/ollama/README.md` for the RTX 4060 profile. No Ollama process or GPU is used by the agent in OpenAI mode.

Tests:

```bash
node --test tests/agent_loop.test.mjs tests/dashboard_transport.test.mjs
uv run pytest tests/test_agent.py tests/test_openai_gateway.py
```

Automated tests use stub model responses; live API/model acceptance remains required. See `docs/06_llm_agent_integration.md`.

## Project requirements and traceability

The SRS is the canonical requirements baseline. The full FR/NFR mapping from implementation and automated tests to live acceptance evidence is in [docs/11_requirements_traceability.md](docs/11_requirements_traceability.md).

## Quality checks

```bash
uv run ruff check .
uv run pyright
uv run pytest
node --test tests/dashboard_transport.test.mjs tests/agent_loop.test.mjs
```

The test suite includes unit tests, an in-process MCP SDK contract test and an actual TCP/Streamable HTTP integration test. These automated tests do not replace live Keycloak, TLS trust, second-device LAN, systemd privilege or performance acceptance on Ubuntu 24.04.

## Infrastructure deployment

Follow [the Ubuntu 24.04 deployment guide](docs/09_ubuntu2404_deployment.md). The intended sequence is PostgreSQL and Keycloak first, then the authenticated native MCP service, and Caddy only after local token validation succeeds.

Keep the firewall restrictive: only the intended HTTPS ingress (TCP 443) should be reachable from the selected demo network. Do not publish PostgreSQL (5432), Keycloak (8080) or MCP (3002) to the LAN.

## Performance benchmark

The benchmark runner uses the official MCP Python Client over Streamable HTTP. It reports p50/p95/p99, success/error counts and host/runtime metadata without recording access tokens or tool output.

```bash
MCP_BENCHMARK_URL=https://mcp.home.arpa/mcp \
MCP_BENCHMARK_ACCESS_TOKEN='<read token>' \
MCP_BENCHMARK_LOG_ALIAS=ssh \
uv run python scripts/benchmark_mcp.py --iterations 100
```

Use a valid bearer token from a protected secret source. Set `MCP_BENCHMARK_LOG_ALIAS` only when the token includes `mcp.logs.read`. Benchmark evidence must be produced on the designated Ubuntu 24.04 host and recorded under `reports/acceptance/`; no benchmark result is assumed by this repository.

## Integration status

The `integration/finalize-ubuntu2404` branch consolidates the Security & Infrastructure implementation with the Technical Lead workstream definition, adds defensive fixes and automated HTTP/performance tooling. It is a release-readiness candidate, **not a claim of completed live acceptance**.

Open acceptance gates include real Keycloak token flows, trusted Caddy TLS from a second LAN client, systemd identity/sandbox inspection, PostgreSQL volume persistence on the target host and measured per-tool p95 latency. Record results and limitations before declaring the project accepted.
