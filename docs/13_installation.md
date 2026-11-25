# Linux Observatory installation and lifecycle

## Supported fresh-install target

The automated installer currently supports:

- Ubuntu 24.04 LTS, amd64 or arm64.
- systemd and journald.
- A working IPv4 LAN interface.
- An interactive terminal with sudo/root access.
- Internet access to install system packages, Python, uv and the pinned container images.

The browser OAuth implementation currently uses the fixed origins `mcp.home.arpa` and `auth.home.arpa`. The installer intentionally uses those same hostnames; custom public domains require a coordinated change to the browser OAuth configuration and are not supported by this installer yet.

## First installation

Clone the repository, enter its root directory, and run the installer:

```bash
git clone https://github.com/tuananh-developer/linux-mcp-agent-server.git
cd linux-mcp-agent-server
sudo bash scripts/install.sh
```

The installer asks for the host's LAN IPv4 address and the first dashboard username, optional email and password. Password entry is hidden. The initial password must contain at least 12 characters.

The installer then:

1. Verifies Ubuntu 24.04 and the CPU architecture.
2. Installs Docker Engine/Compose from Docker's official Ubuntu apt repository when Compose v2 is not already available. It refuses to remove legacy/conflicting container packages.
3. Installs the pinned uv release and Python runtime.
4. Creates a dedicated `linux-mcp-agent` service user and protected application, config, cache and state directories.
5. Generates unique PostgreSQL, Keycloak bootstrap-admin, MCP introspection-client and external agent-client secrets.
6. Creates the Keycloak `linux-agent` realm, the MCP resource server and machine client, plus the first dashboard user.
7. Initializes the AES-256-GCM provider vault master key without exposing the key to the dashboard.
8. Installs and starts the native MCP systemd service.
9. Starts Caddy and exports its internal root CA.
10. Adds managed host entries on the server itself and verifies both MCP and Caddy HTTPS health.

On success, the dashboard is available at:

- `https://mcp.home.arpa/dashboard`
- `https://mcp.home.arpa/assistant`

The local Keycloak issuer is `https://auth.home.arpa/realms/linux-agent`.

## LAN clients, DNS and TLS trust

The installer adds the hostnames to the server's own `/etc/hosts`. It does not manage the LAN router or DNS server. For every other LAN client, create DNS records (or local hosts entries) that map both `mcp.home.arpa` and `auth.home.arpa` to the server's LAN IPv4 address.

Caddy uses an internal certificate authority. The root certificate is saved at:

```
/etc/linux-mcp-agent/caddy-root.crt
```

Copy that certificate to every client and add it to the client's trusted root CA store. On Ubuntu/Debian clients, install it under `/usr/local/share/ca-certificates/` and run `sudo update-ca-certificates`. Some browsers maintain a separate certificate store; import the certificate there if the browser does not use the operating-system trust store.

The installer deliberately does not enable or rewrite UFW/nftables rules because changing firewall policy can cut off SSH or other services. Allow TCP 443 from trusted LAN clients only. Do not expose MCP port 3002, Keycloak port 8080 or PostgreSQL port 5432 to the LAN or Internet.

## First dashboard login and AI provider setup

Sign in with the first dashboard username/password provided during installation. The installer creates a Keycloak user and configures the browser PKCE client.

The AI assistant is enabled but no hosted AI API key is generated or bundled. In the dashboard, select Gemini, OpenAI, OpenRouter or Anthropic, enter a provider key and model, test the connection, and enable the option to save the key on the MCP server. The server stores the API key encrypted per Keycloak subject. Ollama remains an option for a local provider and does not require a hosted API key.

The generated Keycloak bootstrap administrator password and Compose database secret are stored in `/etc/linux-mcp-agent/compose.env` (root-only). The external MCP machine-client credentials are in `/etc/linux-mcp-agent/agent-client.env` (root-only). The MCP introspection secret and other service settings are stored in `/etc/linux-mcp-agent/server.env`.

The provider vault master key is stored at `/etc/linux-mcp-agent/provider-vault.key`. The ciphertext and its lock file are stored under `/var/lib/linux-mcp-agent/`. Back up the master key separately from the ciphertext. Losing the master key makes saved provider keys unrecoverable.

## Service operations

The MCP application runs natively under systemd. PostgreSQL, Keycloak and Caddy run under Docker Compose.

```bash
sudo systemctl status linux-mcp-agent.service
sudo systemctl restart linux-mcp-agent.service
sudo journalctl -u linux-mcp-agent.service -n 100 --no-pager
sudo bash scripts/doctor.sh
```

The application binds to `127.0.0.1:3002`. Caddy exposes the dashboard, assistant and MCP endpoints on TCP 443.

## Upgrade

Use a fresh repository clone or pull the latest `main` in your existing clone. From the repository root:

```bash
git pull --ff-only
sudo bash scripts/upgrade.sh
```

Upgrade preserves:

- `/etc/linux-mcp-agent/server.env` and generated service secrets.
- The provider vault master key and encrypted credential store.
- The Keycloak PostgreSQL named volume, users and clients.
- The Caddy data/config volumes and internal root CA.
- The administrator's log-source allowlist.

The upgrade replaces application code, synchronizes the pinned Python dependencies, restarts MCP, recreates Caddy with the current proxy routes and checks health.

## Recovering a first install that stopped part-way through

The installer writes secrets and configuration before provisioning Keycloak. If it exits after those files exist, rerun the same installer from the same repository clone:

```bash
sudo bash scripts/install.sh --resume
```

Resume reuses the existing Compose password, Keycloak admin password, introspection/client secrets, provider vault key and database volume. It asks for the first dashboard username and password again; if the user already exists, it resets that user's password. Do not remove `/etc/linux-mcp-agent`, `/var/lib/linux-mcp-agent` or Docker volumes to recover a failed installation.

If the failure happened before protected configuration files were generated, inspect the error and run the normal installer again. If the installer reports existing unrecognized files, stop and inspect them rather than overwriting them.

## Uninstall and data retention

Default uninstall removes the application, the systemd unit, managed host entries and the local CA trust entry. It stops the Compose stack but preserves the Keycloak database volume, service configuration, vault master key, encrypted credentials and state directory:

```bash
sudo bash scripts/uninstall.sh
```

For permanent data deletion:

```bash
sudo bash scripts/uninstall.sh --purge-data
```

The purge path requires typing `UNINSTALL` and then `DELETE DATA`. It removes the Keycloak Compose volumes and the local provider vault/configuration. This is irreversible. Docker Engine and uv are left installed because other applications may use them.

## Manual and development modes

The installer is the recommended first-install path for Ubuntu 24.04. Operators can still follow [the manual systemd deployment](../deploy/systemd/README.md). Local development can use `.env.example` and run the application on loopback with `AUTH_MODE=disabled`; never expose that development mode to a LAN.
