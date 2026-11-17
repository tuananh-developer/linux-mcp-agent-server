# systemd deployment

The MCP process is native on the Ubuntu host, runs as the dedicated non-root user `linux-mcp-agent`, and binds only to `127.0.0.1:3000`. The unit deliberately grants no root privileges.

## Journal access design and residual privilege

`linux-mcp-agent.service` sets `SupplementaryGroups=systemd-journal` so the unprivileged service account can invoke `/usr/bin/journalctl` without `sudo` or capabilities. At the application layer, `read_allowed_log` accepts only administrator-configured aliases from `/etc/linux-mcp-agent/log-sources.json` (which map to fixed `.service` units), enforces `shell=False`, bounds line count, execution timeout, and output bytes, and redacts common secret patterns.

**Residual risk:** Membership in `systemd-journal` grants OS-level read visibility across the host systemd journal rather than per-unit ACLs. Because the application enforces strict unit allowlisting and never executes arbitrary commands, this residual privilege is contained to the Python service process and must be reviewed whenever new tools are proposed.

## Systemd sandboxing controls

`deploy/systemd/linux-mcp-agent.service` applies strict service hardening:
- Identity & permissions: `User=linux-mcp-agent`, `Group=linux-mcp-agent`, `SupplementaryGroups=systemd-journal`, `NoNewPrivileges=true`, `UMask=0077`, `RestrictSUIDSGID=true`.
- Filesystem isolation: `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp=true`, `PrivateDevices=true`, `ReadOnlyPaths=/proc /sys`.
- Kernel & execution isolation: `ProtectKernelTunables=true`, `ProtectKernelModules=true`, `ProtectControlGroups=true`, `ProtectClock=true`, `ProtectHostname=true`, `LockPersonality=true`, `MemoryDenyWriteExecute=true`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, `SystemCallArchitectures=native`.

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

The project pins direct dependencies in `pyproject.toml`. Generate and commit `uv.lock` with `uv lock` on a network-connected development machine before using `uv sync --locked` in a clean deployment.

## Upgrade and rollback procedure

### Upgrade
1. Fetch the target release/commit in `/opt/linux-mcp-agent-server` and record the previous commit SHA (`git rev-parse HEAD`).
2. Sync dependencies and run unit checks before restarting:
   ```bash
   cd /opt/linux-mcp-agent-server
   sudo git fetch origin
   sudo git checkout <target-ref>
   sudo uv sync --locked --no-dev
   sudo install -o root -g root -m 0644 deploy/systemd/linux-mcp-agent.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl restart linux-mcp-agent
   curl -fsS http://127.0.0.1:3000/healthz
   ```

### Rollback
If the service fails health checks after an upgrade:
```bash
cd /opt/linux-mcp-agent-server
sudo git checkout <previous-commit-sha>
sudo uv sync --locked --no-dev
sudo install -o root -g root -m 0644 deploy/systemd/linux-mcp-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart linux-mcp-agent
curl -fsS http://127.0.0.1:3000/healthz
```
