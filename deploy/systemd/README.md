# systemd deployment

The MCP process is native on the Ubuntu host, runs as `linux-mcp-agent`, and binds only to `127.0.0.1:3000`. The unit deliberately grants no root privileges. It joins `systemd-journal` only because the journal reader needs to read the configured unit aliases; this group grants broader journal visibility and is a documented residual risk.

## Install

1. Install Git, build tools, `journalctl`, and uv 0.13.6.
2. Clone the repository to `/opt/linux-mcp-agent-server`.
3. Create a dedicated service account and install the project environment:

```bash
sudo useradd --system --home /var/lib/linux-mcp-agent --create-home --shell /usr/sbin/nologin linux-mcp-agent
sudo usermod -aG systemd-journal linux-mcp-agent
sudo install -d -o root -g linux-mcp-agent -m 0750 /etc/linux-mcp-agent
sudo install -o root -g linux-mcp-agent -m 0640 deploy/systemd/server.env.example /etc/linux-mcp-agent/server.env
sudo install -o root -g linux-mcp-agent -m 0640 config/log-sources.example.json /etc/linux-mcp-agent/log-sources.json
sudo install -o root -g root -m 0644 deploy/systemd/linux-mcp-agent.service /etc/systemd/system/
```

Edit `/etc/linux-mcp-agent/server.env`; set `AUTH_MODE=keycloak`, real issuer/resource values, and the introspection client secret. Keep the file mode at `0640` and never commit it.

```bash
cd /opt/linux-mcp-agent-server
sudo uv sync --locked --no-dev
sudo systemctl daemon-reload
sudo systemctl enable --now linux-mcp-agent
sudo systemctl status linux-mcp-agent
curl -fsS http://127.0.0.1:3000/healthz
```

The project currently pins direct dependencies in `pyproject.toml`. Generate and commit `uv.lock` with `uv lock` on a network-connected development machine before using `uv sync --locked` in a clean deployment.
