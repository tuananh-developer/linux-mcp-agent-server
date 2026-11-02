# External AI Agent Integration Boundary

**Document ID:** LMAS-AGENT-001 · **Version:** 1.0

## Scope

This repository implements an MCP Server only. It does not install, host, configure, select, or call an LLM. Model inference, provider credentials, provider fallback, conversation history, and natural-language orchestration belong to the separately deployed AI Agent/MCP Client.

## Integration flow

1. The external AI Agent receives a user request and decides whether MCP tools are needed.
2. Its MCP Client connects to the configured MCP endpoint and authenticates using the documented OAuth policy.
3. The client discovers tools/resources/prompts and invokes only the requested MCP operation.
4. The MCP Server validates authorization and arguments, reads the permitted host data, and returns structured results.
5. The external Agent interprets the result according to its own model/provider and privacy policy.

## Security boundary

- No LLM API keys, model names, provider URLs, or inference services are part of this repository.
- The MCP Server never forwards tool output to a model or third-party service.
- The external Agent must apply its own consent, secret filtering, retention, and provider-routing policy.
- Raw journal output and credentials should not be sent to external model providers.
- MCP authorization does not imply that the external Agent is trusted with every returned datum; apply least privilege and the log-specific scope.

## Acceptance

Validate MCP connectivity independently with MCP Inspector or another standards-compliant MCP Client. Agent/model quality and end-to-end natural-language behavior are tested in the separate Agent project and are not part of this server's acceptance criteria.
