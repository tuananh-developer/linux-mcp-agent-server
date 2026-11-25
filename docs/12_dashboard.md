# Linux Observatory browser dashboard

The browser dashboard is served at / and /dashboard; the optional AI assistant is served at /assistant.

## Data flow

- The browser creates a same-origin MCP Streamable HTTP client for /mcp.
- It discovers the MCP tool registry and requires all eight read-only tools before marking the dashboard connected.
- The overview periodically invokes get_system_metrics, get_disk_usage, list_processes, get_network_stats, get_system_alerts, get_service_status, and check_port.
- Network panels calculate current RX/TX throughput from consecutive cumulative counter samples while retaining total bytes received/sent; the first sample establishes the baseline.
- Overall connection state distinguishes healthy, degraded, expired-auth and offline states. Expired or insufficient Keycloak tokens trigger reconnection instead of leaving a stale connected indicator.
- The process table can be sorted by CPU or RAM and filtered by process name. The service, single-port, and log panels remain explicit, read-only checks.
- HTTP 502/503/504 responses identify the Caddy-to-MCP upstream problem instead of showing a generic connection failure. Partial failures remain visible per dashboard panel.
- Recent journal access is separate and is only attempted after the user presses the log button. It still requires the server journal alias allowlist and the mcp.logs.read scope.
- The AI assistant supports Google Gemini, OpenAI, OpenRouter, Anthropic Claude, and Ollama. OpenRouter uses the OpenAI-compatible API adapter; select a free model ID (for example `nvidia/nemotron-3-ultra-550b-a55b:free`) and provide an OpenRouter API key. Free model availability and limits are controlled by OpenRouter and upstream providers.
- The model gateway converts provider-specific tool calls into one bounded internal format. Tool execution still happens through the same authenticated MCP client and only uses tools advertised by the server.
- Provider API keys are accepted only in authenticated, same-origin `/agent/test` and `/agent/chat` requests. When the user opts in, the server encrypts the key with AES-256-GCM and persists ciphertext only in `/var/lib/linux-mcp-agent/provider-credentials.json`. Records are scoped to the authenticated Keycloak `sub` and provider; the subject and API key are not stored in plaintext. The credential-list endpoint returns provider/model metadata only and never returns the key. The browser keeps newly entered keys in module memory only and never writes them to localStorage, cookies or IndexedDB.
- OpenAI, Gemini, and Anthropic requests are sent to their fixed official API origins. Ollama is restricted to HTTP loopback on the MCP host; arbitrary remote Ollama URLs are rejected.

## Security boundaries

- The MCP bearer token is held in JavaScript memory only. It is not persisted to localStorage or cookies. Provider API keys are a separate credential type: when the user explicitly opts in, they are saved encrypted on the MCP host and are never returned to the browser.
- Browser requests are same-origin and carry the same bearer token to the MCP endpoint. The browser cannot choose an arbitrary host, shell command, remote port target, or filesystem path.
- The dashboard uses textContent for host-provided values and log output; it does not render process names or journal messages as HTML.
- The dashboard is read-only. It does not start/stop services, terminate processes, edit files, or issue remote scans.
- Network counters are cumulative byte counters, not calculated throughput rates.
- Service inspection remains constrained by ALLOWED_SYSTEMD_UNITS; a service that is not allowlisted is shown as unavailable.

## Run

Run `bash scripts/start-demo.sh`. It ensures the local MCP health check passes, configures Caddy to proxy to the actual MCP_PORT, exports the Caddy root CA, and verifies the HTTPS /healthz route before reporting the dashboard URLs. Open `https://mcp.home.arpa/dashboard`; the assistant is at `https://mcp.home.arpa/assistant`.

The browser device must trust the Caddy local root CA. The startup helper exports it to `~/.config/linux-mcp-agent/caddy-root.crt`. Transfer that file to the browser device, then run `bash scripts/install-caddy-ca.sh` there and restart the browser. To export it again later, run `bash scripts/export-caddy-ca.sh`.

Keycloak login is handled by the browser through Authorization Code + PKCE (S256). `scripts/start-demo.sh` creates or updates the public `linux-observatory-browser` client in the existing realm, including its redirect origin, CORS origin, `mcp.read` scope and MCP audience mapper. The user clicks **Đăng nhập bằng Keycloak**; no CLI token request or copy/paste is required.

Create a normal user once in the `linux-agent` realm from the Keycloak Admin Console (`https://auth.home.arpa/admin/`): select realm `linux-agent`, create a user, set a non-temporary password, and keep self-registration disabled. The account is used only for browser sign-in; the MCP server still validates the audience and `mcp.read` scope through its private introspection client.

The browser keeps access and refresh tokens in JavaScript memory and refreshes the access token before expiry while the Keycloak session remains valid. Only the short-lived PKCE state/verifier transaction is kept in `sessionStorage` across the redirect; tokens are never persisted there, in localStorage, cookies or the database. Reloading the page restarts the redirect flow; an active Keycloak SSO session normally avoids re-entering credentials. Disconnect clears the in-memory tokens.

### Provider credential vault

The credential vault belongs to one Linux Observatory deployment and is partitioned by Keycloak subject. A user can store one active API key for each hosted provider (Gemini, OpenAI, OpenRouter and Anthropic); Ollama does not use an API key. Vault endpoints never accept a browser-supplied user ID: they derive ownership from the `sub` claim in the server-validated Keycloak token. `GET /agent/credentials` returns only provider/model/update metadata, and `DELETE /agent/credentials/{provider}` deletes only the caller's credential for that provider.

Keys are encrypted with AES-256-GCM. The systemd service reads a 32-byte master key through `LoadCredential=provider-vault-key:/etc/linux-mcp-agent/provider-vault.key`; systemd exposes a private runtime copy through `CREDENTIALS_DIRECTORY`. The source key is owned by root and has mode `0600`. Ciphertext is stored in `/var/lib/linux-mcp-agent/provider-credentials.json` within a `0700` state directory; the store and lock files have mode `0600`. The master key is separate from the encrypted data. Back up both separately; losing the master key makes stored credentials unrecoverable. Do not copy the same master key to separate installations. The demo launcher creates an installation-specific key in `~/.config/linux-mcp-agent/` and stores its encrypted records in `~/.local/state/linux-mcp-agent/`.

The browser requests `mcp.logs.read` as an optional scope. Journal data is still read only after the user explicitly clicks the log button.

For AI chat, connect MCP, choose Gemini, OpenAI, OpenRouter, Anthropic, or Ollama in the Nhà cung cấp AI panel, enter a model ID and (for hosted providers) your own API key, then select **Kiểm tra kết nối**. To persist the key, select **Lưu API key đã mã hóa trên MCP Server** before checking; after the provider confirms the selected model is available, the server stores the key encrypted and clears it from the input. On a later visit, the server returns only saved provider/model metadata and uses the encrypted key internally after the same Keycloak subject authenticates. Leave the API key field empty to use the saved key, or enter a new one to replace it. Uncheck the option or press **Xóa cấu hình và API key** to remove that provider's server-side credential. Ollama requires no API key and must be listening on the MCP host loopback address. Provider usage may incur charges according to the provider's billing plan.

The UI refreshes the overview every 5 seconds. Clicking Làm mới requests a new snapshot immediately. The dashboard does not persist telemetry or create a metrics history database; the line chart retains up to 60 samples (about 5 minutes) in that browser tab.