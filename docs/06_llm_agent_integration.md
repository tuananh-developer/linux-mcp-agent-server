# Agentic AI integration and acceptance

**Topic:** Build and Configure an MCP Server for Agentic AI in Linux (Linux OSS 2026, topic 15).

## Required outcome

The course requires practical Linux tools integrated with an AI agent and a demonstration of real interaction with Linux services. MCP Inspector is useful protocol evidence, but does not replace the AI demonstration. Read-only tools are a team scope decision, not a restriction imposed by the topic.

## Implementation

- The Python MCP server owns Linux access, allowlists, argument validation and authorization.
- The dashboard AI Assistant is the agent/MCP client. It retains conversation state in tab memory and implements a bounded model/tool loop.
- OpenAI Responses API performs inference by default (`OPENAI_MODEL`, default `gpt-6-luna`). Local Ollama remains an optional provider.
- `/agent/chat` is an authenticated model gateway, not a Linux tool execution endpoint. It supplies a server-owned system prompt and derives tool schemas from MCP registration.
- Tool selection is model-directed. The browser validates tool names against discovery, invokes `/mcp`, shows results, then submits those observations for another inference step.
- Existing external AI/MCP clients can continue to use `/mcp` independently.

## Configuration and access

The default provider is OpenAI Responses API. Set `AGENT_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-6-luna` and `OPENAI_MAX_OUTPUT_TOKENS=1024` in the backend environment. Restart the application after changes. The key stays server-side and is never included in frontend assets, status messages or model input. The OpenAI endpoint is fixed HTTPS; redirects are rejected. Use an API project with valid billing and model access. The status endpoint does not make a paid inference request; it reports key presence, not verified model access.

For optional local inference, set `AGENT_PROVIDER=ollama`, install Ollama, pull `qwen3:4b` and use the local profile documented in `deploy/ollama/README.md`.

The gateway checks allowed Host/Origin and the base scope in Keycloak mode. Actual tool calls still pass through MCP authorization, including the additional log scope. MCP Bearer credentials are not passed to either model provider.

## Privacy and execution bounds

In API mode, questions, conversation history and selected tool results are sent to OpenAI. In Ollama mode, they go to the configured loopback inference service. The UI discloses the active boundary. Log tools require explicit log sharing; changing the checkbox clears the conversation. Secret redaction is best effort. Do not submit credentials or sensitive host data without the appropriate permission.

OpenAI requests use `store=false`, with provider retention policies still applicable. The backend persists no chat history. Tool outputs remain untrusted data, not instructions.

The loop is bounded to five model rounds and ten tool calls per user turn. The API adapter disables reasoning and parallel tool calls and caps output at the configured token limit. Per-turn usage is shown in the UI; billing/project spending controls are separate. Cancellation prevents subsequent steps but may not stop an already-running remote request or its billing. Model answers require review.

## Required live acceptance

Record provider/model ID, API usage or Ollama version, host CPU/RAM/GPU, OS, commands, screenshots/tool traces, timings, failures and limitations. Do not mark these complete based on mocked tests.

1. Ask for a general health check. Verify model-selected metrics/disk/process tool calls and that the final answer matches their observed values and timestamps.
2. Ask for the five largest memory consumers. Verify actual MCP arguments and output, and compare against host tools under the same observation conditions.
3. Enable log consent and ask for recent entries of a configured Linux service alias. Verify journald access, tool trace and a grounded explanation; empty output must not be presented as proof a service failed.
4. Disable log consent, ask for logs, and verify no journal call is executed. Test missing log scope separately in Keycloak mode.
5. Remove the API key, simulate exhausted quota, or choose an unavailable model (stop Ollama in local mode). The UI must show a setup/error state rather than generate a fake answer.
6. Try an unsupported mutation request. The agent must explain its limited tools and must not execute arbitrary commands.
7. Exercise a follow-up question, cancellation and new-chat clearing.

## Automated evidence and current limit

Python tests validate the model gateway, filtering, bounds, Origin policy and authentication. JavaScript tests validate multi-step model/tool flow, unknown tools, log consent, cancellation and loop termination using test doubles. These tests do not establish actual Ollama model performance or production TLS/LAN behavior. Live model acceptance remains pending until valid API access or a local model is configured and the scenarios are exercised.

## RTX 4060 8 GiB starting profile

The gateway defaults to 4096 context tokens with `qwen3:4b`; set `OLLAMA_CONTEXT_LENGTH` in the project environment to change it (2048–32768). It sends this value explicitly on every generation request. One concurrent generation per process is enforced by the gateway. For one loaded model and one parallel request across the Ollama service, apply `deploy/ollama/rtx4060.conf` following `deploy/ollama/README.md`. The profile targets VRAM headroom, not an exact 4 GiB cap; real-model validation on the GPU remains pending.
